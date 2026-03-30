"""
캘린더 슬래시 커맨드 핸들러
/today  /week  /add  /free  /cancel  /remind  /help
그 외 자연어 메시지 → Claude API → 캘린더 액션
"""
import logging
import re
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from telegram.ext import ContextTypes
import pytz

import db as db
from config import TIMEZONE, DEFAULT_REMINDER_MINUTES, MAX_MESSAGE_LENGTH
from constants import (
    KEY_HISTORY, KEY_TEAM_INPUT_MODE, KEY_PENDING_TEAM_EVENT,
    SENTINEL_PRIORITY_BUTTONS,
)
from models.user import UserStatus
from services.rate_limiter import is_allowed
from services import claude_service, calendar_service, intent_cache
from services.calendar_service import get_auth_url
from services.oauth_server import wait_for_oauth
from services.scheduler_service import schedule_reminders_for_event
from handlers.wizard_handler import wizard_start, team_wizard_start, cancel_wizard_start, wizard_handle_text
from handlers.team_handler import PRIORITY_BUTTONS

tz = pytz.timezone(TIMEZONE)


def _clear_session(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """대화 세션의 stale 상태를 초기화합니다. /start, /status 등 진입점에서 호출."""
    for key in (KEY_HISTORY, KEY_TEAM_INPUT_MODE, KEY_PENDING_TEAM_EVENT):
        ctx.user_data.pop(key, None)


def _approved(telegram_id: int) -> bool:  # noqa: D401
    record = db.get_user(telegram_id)
    return record is not None and record.get("status") == UserStatus.APPROVED


def _now() -> datetime:
    return datetime.now(tz)


def _team_events_as_gcal(t_min: str, t_max: str) -> list[dict]:
    """DB 팀 이벤트를 Google Calendar 포맷으로 변환 (목록 병합용).
    title 앞에 [팀] 머리말 추가.
    """
    team_events = db.get_team_events_by_range(t_min, t_max)
    result = []
    for te in team_events:
        result.append({
            "summary": f"[팀] {te['title']}",
            "start": {"dateTime": te["start_dt"]},
            "end":   {"dateTime": te["end_dt"]},
        })
    return result


# ── 하단 고정 메뉴 (ReplyKeyboardMarkup) ──────────────────

def get_main_menu() -> ReplyKeyboardMarkup:
    """
    승인된 사용자에게 항상 표시되는 하단 고정 메뉴.
    6개 버튼: 등록(2) / 조회+빈시간(2) / 취소+도움말(2)
    날씨는 도움말 인라인 버튼 안으로 이동.
    """
    keyboard = [
        [KeyboardButton("📅 일정 등록"),    KeyboardButton("👥 팀 일정 등록")],
        [KeyboardButton("📋 일정 조회"),    KeyboardButton("⏱ 빈 시간 찾기")],
        [KeyboardButton("🗑 일정 취소"),    KeyboardButton("❓ 도움말")],
    ]
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        input_field_placeholder="메뉴를 선택하거나 자연어로 입력하세요",
    )


# ── /help ────────────────────────────────────────────────

def _help_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📖 시작 가이드",   callback_data="help:guide"),
        ],
        [
            InlineKeyboardButton("📅 개인 일정 설명", callback_data="help:personal"),
            InlineKeyboardButton("👥 팀 일정 설명",  callback_data="help:team"),
        ],
        [
            InlineKeyboardButton("🔔 리마인더 설정", callback_data="help:remind"),
            InlineKeyboardButton("🌤 오늘 날씨",     callback_data="help:weather"),
        ],
    ])


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *스케줄 챗봇 도움말*\n\n"
        "아래 버튼을 탭하거나 자연어로 말씀해 주세요.\n\n"
        "💬 *자연어 예시*\n"
        "• 내일 오후 3시 팀 미팅 잡아줘\n"
        "• 이번 주 일정 보여줘\n"
        "• 금요일 회의 취소해줘\n"
        "• 4월 2주차 2시간 비는 시간 찾아줘\n"
        "• 팀 미팅 30분 전에 알려줘\n\n"
        "_📖 시작 가이드를 탭하면 전체 사용법을 볼 수 있습니다._"
    )
    msg = update.message or (update.callback_query and update.callback_query.message)
    if msg:
        await msg.reply_text(text, parse_mode="Markdown", reply_markup=_help_keyboard())


async def help_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """도움말 인라인 버튼 처리."""
    import asyncio
    from services.calendar_service import get_auth_url
    from services.oauth_server import wait_for_oauth
    from handlers.auth_handler import cmd_status

    query = update.callback_query
    await query.answer()
    action = query.data.split(":")[1]

    back_btn = InlineKeyboardMarkup([[
        InlineKeyboardButton("◀ 도움말로", callback_data="help:back")
    ]])

    if action == "back":
        await cmd_help(update, ctx)
        return

    elif action == "guide":
        await query.message.reply_text(
            "📖 *스케줄 챗봇 시작 가이드*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "*1️⃣ 이용 신청*\n"
            "`/start` 입력 → 이름·부서·목적 입력\n"
            "→ 관리자 승인 대기\n\n"
            "*2️⃣ Google Calendar 연동*\n"
            "승인 시 \\[📅 Google Calendar 연동하기\\] 버튼 자동 전송\n"
            "→ 버튼 탭 → 구글 로그인\n"
            "💻 PC: 자동 완료\n"
            "📱 모바일: \\[📨 텔레그램으로 코드 전송\\] 탭 → 코드 붙여넣기\n\n"
            "*3️⃣ 기능 사용*\n"
            "하단 메뉴 버튼 또는 자연어로 대화\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📅 *개인 일정 vs 👥 팀 일정*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "📅 *개인 일정*\n"
            "• 나만의 Google Calendar에 저장\n"
            "• 다른 팀원에게 내용 비공개\n"
            "• 팀 일정 등록 시 충돌 감지에는 참여\n"
            "• 예: _내일 오후 3시 치과 예약 잡아줘_\n\n"
            "👥 *팀 일정*\n"
            "• 팀 공용 캘린더에도 함께 기록\n"
            "• 등록 시 중요도 선택 필수\n"
            "  🔴 필수 — 변경 불가\n"
            "  🟡 조율가능 — 협의 요청\n"
            "  🟢 자유 — 알림만\n"
            "• 팀원 일정과 충돌 자동 감지·조율\n"
            "• 예: _팀 회의 다음 주 월요일 10시로 잡아줘_\n\n"
            "💡 여행·출장 등 종일 일정은 프레임으로 처리\n"
            "→ 그 안에 세부 일정 자유롭게 추가 가능\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💬 *자연어 예시*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "• 내일 오후 3시 치과 예약 잡아줘\n"
            "• 팀 회의 다음 주 월요일 10시로 잡아줘\n"
            "• 이번 주 일정 보여줘\n"
            "• 4월 2주차 3시간 비는 시간 찾아줘\n"
            "• 금요일 미팅 취소해줘\n"
            "• 다음 주 팀 미팅 1시간 전에 알려줘",
            parse_mode="Markdown",
            reply_markup=back_btn,
        )

    elif action == "today":
        await cmd_today(update, ctx)

    elif action == "week":
        await cmd_week(update, ctx)

    elif action == "free":
        await cmd_free(update, ctx)

    elif action == "add":
        await query.message.reply_text(
            "📅 *개인 일정 등록*\n\n"
            "자연어로 입력해 주세요.\n\n"
            "예시\n"
            "• _내일 오후 2시 치과 예약 1시간_\n"
            "• _5월 1일부터 5일까지 매일 오전 9시 스탠드업_\n"
            "• _다음 주 금요일 오후 6시 저녁 약속_",
            parse_mode="Markdown",
            reply_markup=get_main_menu(),
        )

    elif action == "delete":
        await query.message.reply_text(
            "🗑 *일정 취소*\n\n"
            "취소할 일정 이름을 말씀해 주세요.\n\n"
            "예시\n"
            "• _금요일 팀 미팅 취소해줘_\n"
            "• _치과 예약 삭제해줘_",
            parse_mode="Markdown",
            reply_markup=get_main_menu(),
        )

    elif action == "remind":
        await query.message.reply_text(
            "🔔 *리마인더 설정*\n\n"
            "알림 받을 일정과 시간을 말씀해 주세요.\n\n"
            "예시\n"
            "• _팀 미팅 30분 전에 알려줘_\n"
            "• _내일 치과 예약 1시간 전, 10분 전에 알려줘_",
            parse_mode="Markdown",
            reply_markup=get_main_menu(),
        )

    elif action == "personal":
        await query.message.reply_text(
            "📅 *개인 일정*\n\n"
            "나만의 Google Calendar에 저장됩니다.\n"
            "다른 팀원에게 내용은 공개되지 않지만,\n"
            "팀 일정 충돌 감지에는 참여합니다.\n\n"
            "💬 *입력 예시*\n"
            "• 내일 오후 3시 치과 예약 잡아줘\n"
            "• 5월 1\\~5일 여행 일정 넣어줘\n"
            "• 매주 월요일 오전 9시 스탠드업 추가해줘",
            parse_mode="Markdown",
            reply_markup=back_btn,
        )

    elif action == "team":
        await query.message.reply_text(
            "👥 *팀 일정 등록*\n\n"
            "팀 공용 캘린더에 함께 기록됩니다.\n"
            "등록 시 중요도를 선택하면 팀원 일정과\n"
            "충돌을 자동으로 감지·조율합니다.\n\n"
            "🔴 필수 — 변경 불가 \\(최우선\\)\n"
            "🟡 조율가능 — 협의 요청\n"
            "🟢 자유 — 알림만\n\n"
            "💬 *입력 예시*\n"
            "• 팀 회의 다음 주 월요일 10시로 잡아줘\n"
            "• 전체 미팅 4월 3일 오후 2시 팀 일정으로\n"
            "• 공용 일정으로 금요일 오후 5시 회식 추가해줘",
            parse_mode="Markdown",
            reply_markup=back_btn,
        )
        ctx.user_data[KEY_TEAM_INPUT_MODE] = True

    elif action == "connect":
        uid = query.from_user.id
        url = get_auth_url(uid)
        await query.message.reply_text(
            "🔗 *Google Calendar 연동*\n\n"
            "💻 PC: 링크 열기 → Google 허용 → 자동 완료 ✨\n\n"
            "📱 모바일: 링크 탭 → 허용\n"
            "→ \\[📨 텔레그램으로 코드 전송\\] 탭\n"
            "→ 봇 채팅창에 코드 붙여넣기\n\n"
            f"[👉 인증 링크 열기]({url})\n\n"
            "⏰ 5분 내에 완료해 주세요.",
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
        asyncio.create_task(wait_for_oauth(uid, ctx.bot))

    elif action == "status":
        from handlers.auth_handler import cmd_status
        await cmd_status(update, ctx)

    elif action == "weather":
        await cmd_weather(update, ctx)


# ── /today ───────────────────────────────────────────────

def _reply_target(update: Update):
    """message 또는 callback_query.message 를 반환."""
    if update.message:
        return update.message
    if update.callback_query:
        return update.callback_query.message
    return None


async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _approved(uid):
        msg = _reply_target(update)
        if msg: await msg.reply_text("❌ 승인된 사용자만 이용 가능합니다. /start")
        return

    now   = _now()
    t_min = now.replace(hour=0,  minute=0,  second=0,  microsecond=0).isoformat()
    t_max = now.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()

    google_warn = None
    try:
        personal = calendar_service.list_events(uid, t_min, t_max)
    except PermissionError as e:
        personal    = []
        google_warn = str(e)

    team_gcal = _team_events_as_gcal(t_min, t_max)
    all_events = sorted(
        personal + team_gcal,
        key=lambda e: e["start"].get("dateTime", ""),
    )

    if not all_events:
        text = f"📋 오늘 ({now.strftime('%m/%d %a')}) 일정이 없습니다."
        if google_warn:
            text += f"\n\n⚠️ {google_warn}"
    else:
        lines = [f"📋 *오늘 일정* ({now.strftime('%m/%d %a')})\n"]
        lines.append(calendar_service.format_event_list(all_events))
        if google_warn:
            lines.append(f"\n⚠️ _Google Calendar 미연동 — 개인 일정 제외_")
        text = "\n".join(lines)

    msg = _reply_target(update)
    if msg: await msg.reply_text(text, parse_mode="Markdown", reply_markup=get_main_menu())


# ── /week ────────────────────────────────────────────────

async def cmd_week(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _approved(uid):
        msg = _reply_target(update)
        if msg: await msg.reply_text("❌ 승인된 사용자만 이용 가능합니다. /start")
        return

    now        = _now()
    week_start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    week_end   = (week_start + timedelta(days=6)).replace(hour=23, minute=59, second=59)

    wk_min = week_start.isoformat()
    wk_max = week_end.isoformat()

    google_warn = None
    try:
        personal = calendar_service.list_events(uid, wk_min, wk_max)
    except PermissionError as e:
        personal    = []
        google_warn = str(e)

    team_gcal = _team_events_as_gcal(wk_min, wk_max)
    all_events = sorted(
        personal + team_gcal,
        key=lambda e: e["start"].get("dateTime", ""),
    )

    span = f"{week_start.strftime('%m/%d')} ~ {week_end.strftime('%m/%d')}"
    if not all_events:
        text = f"📋 이번 주 ({span}) 일정이 없습니다."
        if google_warn:
            text += f"\n\n⚠️ {google_warn}"
    else:
        lines = [f"📋 *이번 주 일정* ({span})\n"]
        lines.append(calendar_service.format_event_list(all_events))
        if google_warn:
            lines.append(f"\n⚠️ _Google Calendar 미연동 — 개인 일정 제외_")
        text = "\n".join(lines)

    msg = _reply_target(update)
    if msg: await msg.reply_text(text, parse_mode="Markdown", reply_markup=get_main_menu())


# ── /free ────────────────────────────────────────────────

async def cmd_free(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _approved(uid):
        msg = _reply_target(update)
        if msg: await msg.reply_text("❌ 승인된 사용자만 이용 가능합니다. /start")
        return

    today = _now().strftime("%Y-%m-%d")
    try:
        slots_by_day = calendar_service.find_free_slots(uid, today, today, duration_hours=1.0)
    except PermissionError as e:
        msg = _reply_target(update)
        if msg: await msg.reply_text(str(e), reply_markup=get_main_menu())
        return

    slots = slots_by_day.get(today, [])
    if not slots:
        text = "오늘은 비는 시간이 없습니다. 😅"
    else:
        lines = ["⏱ *오늘 비는 시간대*\n"] + [f"• {s}" for s in slots]
        text = "\n".join(lines)

    msg = _reply_target(update)
    if msg: await msg.reply_text(text, parse_mode="Markdown", reply_markup=get_main_menu())


# ── /weather ─────────────────────────────────────────────

async def cmd_weather(update: Update, ctx: ContextTypes.DEFAULT_TYPE, week: bool = False):
    """오늘 날씨 또는 5일 예보 표시."""
    from services.weather_service import get_today_summary, get_week_forecast
    msg = _reply_target(update)
    if not msg:
        return
    if week:
        text = get_week_forecast()
    else:
        today = _now()
        summary = get_today_summary()
        text = f"🌤 *오늘 날씨* ({today.strftime('%m/%d %a')})\n\n{summary}"
    await msg.reply_text(text, parse_mode="Markdown", reply_markup=get_main_menu())


# ── /schedule_view — 일정 조회 인라인 선택 ───────────────

def _view_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("오늘",    callback_data="view:today"),
        InlineKeyboardButton("이번 주", callback_data="view:week"),
        InlineKeyboardButton("이번 달", callback_data="view:month"),
    ]])


async def cmd_schedule_view(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """📋 일정 조회 버튼 → 기간 선택 인라인 키보드."""
    msg = _reply_target(update)
    if msg:
        await msg.reply_text(
            "📋 *일정 조회*\n조회할 기간을 선택하세요.",
            parse_mode="Markdown",
            reply_markup=_view_keyboard(),
        )


async def schedule_view_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """view:today / view:week / view:month 콜백 처리."""
    query = update.callback_query
    await query.answer()
    period = query.data.split(":")[1]

    if period == "today":
        await cmd_today(update, ctx)
    elif period == "week":
        await cmd_week(update, ctx)
    elif period == "month":
        uid  = update.effective_user.id
        now  = _now()
        m_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # 다음 달 1일 - 1초 = 이번 달 말일
        if m_start.month == 12:
            m_end = m_start.replace(year=m_start.year + 1, month=1, day=1) - timedelta(seconds=1)
        else:
            m_end = m_start.replace(month=m_start.month + 1, day=1) - timedelta(seconds=1)

        google_warn = None
        try:
            personal = calendar_service.list_events(uid, m_start.isoformat(), m_end.isoformat())
        except PermissionError as e:
            personal    = []
            google_warn = str(e)

        team_gcal  = _team_events_as_gcal(m_start.isoformat(), m_end.isoformat())
        all_events = sorted(personal + team_gcal, key=lambda e: e["start"].get("dateTime", ""))
        span       = f"{m_start.strftime('%m/%d')} ~ {m_end.strftime('%m/%d')}"

        if not all_events:
            text = f"📋 이번 달 ({span}) 일정이 없습니다."
        else:
            lines = [f"📋 *이번 달 일정* ({span})\n"]
            lines.append(calendar_service.format_event_list(all_events))
            if google_warn:
                lines.append("\n⚠️ _Google Calendar 미연동 — 개인 일정 제외_")
            text = "\n".join(lines)

        msg = _reply_target(update)
        if msg:
            await msg.reply_text(text, parse_mode="Markdown", reply_markup=get_main_menu())


# ── 자연어 메시지 처리 + 하단 메뉴 버튼 처리 ──────────────

# 하단 메뉴 버튼 텍스트 목록 (NLP로 넘기지 않고 직접 처리)
_MENU_BUTTONS = {"📅 일정 등록", "👥 팀 일정 등록", "📋 일정 조회", "⏱ 빈 시간 찾기", "🗑 일정 취소", "❓ 도움말"}

# ── Pre-filter: 명확한 패턴은 Claude 미호출로 직접 처리 ────
# (날짜/시간이 포함된 복잡한 요청은 매칭 안 됨 → Claude로)
_PREFILTER: list[tuple[re.Pattern, str]] = [
    # 오늘 일정
    (re.compile(r"^오늘\s*(일정|스케줄|뭐\s*(있|해|있어|해)[?？]?)\s*[?？]?$"), "today"),
    # 이번 주 일정
    (re.compile(r"^이번\s*주\s*(일정|스케줄|뭐\s*(있|있어)[?？]?)?\s*[?？]?$"), "week"),
    # 오늘 빈 시간
    (re.compile(r"^오늘\s*(빈\s*시간|언제\s*비어|비는\s*시간)[?？]?$"), "free"),
    # 날씨
    (re.compile(r"^(오늘\s*)?(날씨|기온|온도|비\s*와[?？]?|눈\s*와[?？]?)[?？]?$"), "weather"),
    (re.compile(r"^이번\s*주\s*날씨[?？]?$"), "weather_week"),
    # 도움말
    (re.compile(r"^(도움말|사용법|기능\s*알려줘|어떻게\s*(써|사용))[?？]?$"), "help"),
]


def _prefilter_action(text: str) -> str | None:  # noqa: D401
    """명확한 패턴 매칭 시 액션 반환. 매칭 없으면 None."""
    t = text.strip()
    for pattern, action in _PREFILTER:
        if pattern.match(t):
            return action
    return None


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid       = update.effective_user.id
    user_text = update.message.text

    if not _approved(uid):
        await update.message.reply_text(
            "❌ 이용 권한이 없습니다.\n/start 로 상태를 확인하거나 /register 로 신청하세요."
        )
        return

    # 1. 위저드 진행 중이면 위저드에 텍스트 전달
    if await wizard_handle_text(update, ctx):
        return

    # 2. 하단 메뉴 버튼 처리
    if user_text == "📅 일정 등록":
        await wizard_start(update, ctx)
        return
    if user_text == "👥 팀 일정 등록":
        await team_wizard_start(update, ctx)
        return
    if user_text == "📋 일정 조회":
        await cmd_schedule_view(update, ctx)
        return
    if user_text == "⏱ 빈 시간 찾기":
        await cmd_free(update, ctx)
        return
    if user_text == "🗑 일정 취소":
        await cancel_wizard_start(update, ctx)
        return
    if user_text == "❓ 도움말":
        await cmd_help(update, ctx)
        return

    # 3. Pre-filter: 명확한 패턴은 Claude 미호출로 직접 처리
    action = _prefilter_action(user_text)
    if action == "today":
        await cmd_today(update, ctx)
        return
    if action == "week":
        await cmd_week(update, ctx)
        return
    if action == "free":
        await cmd_free(update, ctx)
        return
    if action == "weather":
        await cmd_weather(update, ctx)
        return
    if action == "weather_week":
        await cmd_weather(update, ctx, week=True)
        return
    if action == "help":
        await cmd_help(update, ctx)
        return

    # 4. 입력 길이 검증
    if len(user_text) > MAX_MESSAGE_LENGTH:
        await update.message.reply_text(
            f"⚠️ 메시지가 너무 깁니다. {MAX_MESSAGE_LENGTH}자 이내로 입력해 주세요.",
            reply_markup=get_main_menu(),
        )
        return

    # 5. Rate limiting
    if not is_allowed(uid):
        await update.message.reply_text(
            "⚠️ 요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.",
            reply_markup=get_main_menu(),
        )
        return

    # 6. 자연어 → Claude API (캐시 우선 조회)
    await update.message.chat.send_action("typing")
    history = ctx.user_data.get(KEY_HISTORY, [])

    # 팀 일정 입력 모드: is_team 확실히 인식시키기 위해 키워드 주입
    if ctx.user_data.pop(KEY_TEAM_INPUT_MODE, False):
        user_text = user_text + " (팀 일정으로 등록해줘)"

    intents = intent_cache.get(uid, user_text)
    if intents is None:
        try:
            intents = await claude_service.parse_intent(user_text, history)
        except TimeoutError:
            await update.message.reply_text(
                "⚠️ 응답 시간이 초과됐습니다. 잠시 후 다시 시도해 주세요.",
                reply_markup=get_main_menu(),
            )
            return
        except Exception as e:
            await update.message.reply_text(
                "⚠️ 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
                reply_markup=get_main_menu(),
            )
            return
        intent_cache.put(uid, user_text, intents)

    history.append({"role": "user", "content": user_text})
    ctx.user_data[KEY_HISTORY] = history[-12:]

    # 여러 tool_use를 순차 처리 (예: 날짜 범위 일정 등록)
    replies = []
    for intent in intents:
        tool = intent["tool"]
        args = intent["args"]

        try:
            reply = await _dispatch(uid, tool, args, ctx)
        except PermissionError:
            reply = "⚠️ Google Calendar가 연동되지 않았습니다. /connect 를 입력해 주세요."
        except Exception as e:
            reply = f"⚠️ 처리 중 오류가 발생했습니다: {e}"

        # 팀 일정 우선순위 선택 버튼 (첫 번째만 처리)
        if SENTINEL_PRIORITY_BUTTONS in reply:
            from handlers.team_handler import PRIORITY_BUTTONS
            text = reply.replace(SENTINEL_PRIORITY_BUTTONS, "").strip()
            await update.message.reply_text(
                text, parse_mode="Markdown",
                reply_markup=PRIORITY_BUTTONS,
            )
            return

        replies.append(reply)

    # 여러 결과를 하나로 합쳐서 전송 (5개 이하면 합치고, 초과면 요약)
    combined = "\n\n".join(r for r in replies if r)
    await update.message.reply_text(
        combined, parse_mode="Markdown",
        disable_web_page_preview=True,
        reply_markup=get_main_menu(),
    )


def _to_rfc3339(dt_str: str, end: bool = False) -> str:
    """
    Claude가 반환한 날짜/시간 문자열을 Google Calendar API용 RFC 3339로 정규화.
    "2026-04-01"            → "2026-04-01T00:00:00+09:00"  (end=False)
    "2026-04-30"            → "2026-04-30T23:59:59+09:00"  (end=True)
    "2026-04-01T09:00:00"   → "2026-04-01T09:00:00+09:00"  (타임존 보완)
    이미 올바른 형식이면 그대로 반환.
    """
    if not dt_str:
        return dt_str
    # 이미 타임존 포함된 경우
    if "+" in dt_str or dt_str.endswith("Z"):
        return dt_str
    # 날짜만 있는 경우 (YYYY-MM-DD)
    if len(dt_str) == 10:
        suffix = "T23:59:59+09:00" if end else "T00:00:00+09:00"
        return dt_str + suffix
    # 시간은 있지만 타임존 없는 경우
    if "T" in dt_str and "+" not in dt_str:
        return dt_str + "+09:00"
    return dt_str


async def _dispatch(uid: int, tool: str, args: dict, ctx: ContextTypes.DEFAULT_TYPE) -> str:
    now = _now()

    if tool == "plain_reply":
        return args.get("message", "")

    elif tool == "create_event":
        # 팀 일정이면 우선순위 선택 먼저
        if args.get("is_team"):
            from handlers.team_handler import PRIORITY_BUTTONS
            ctx.user_data[KEY_PENDING_TEAM_EVENT] = {
                "title":       args["title"],
                "start":       args["start"],
                "end":         args["end"],
                "location":    args.get("location", ""),
                "description": args.get("description", ""),
                "attendees":   args.get("attendees", []),
            }
            start_str = args["start"][:16].replace("T", " ")
            return (
                f"📅 *{args['title']}* ({start_str})\n\n"
                f"팀 일정 중요도를 선택해 주세요.\n"
                f"_(충돌 발생 시 우선순위에 따라 자동 조율됩니다)_\n\n"
                + SENTINEL_PRIORITY_BUTTONS
            )

        event = calendar_service.create_event(
            uid,
            title=args["title"],
            start=args["start"],
            end=args["end"],
            location=args.get("location", ""),
            description=args.get("description", ""),
            attendees=args.get("attendees", []),
        )
        schedule_reminders_for_event(
            uid, event["id"], args["title"], args["start"],
            DEFAULT_REMINDER_MINUTES,
        )
        return calendar_service.format_event(event)

    elif tool == "list_events":
        # Claude가 "2026-04-01" 날짜만 반환할 수 있음 → RFC 3339로 정규화
        t_min = _to_rfc3339(args["time_min"], end=False)
        t_max = _to_rfc3339(args["time_max"], end=True)
        try:
            personal = calendar_service.list_events(uid, t_min, t_max)
        except PermissionError:
            personal = []
        team_gcal = _team_events_as_gcal(t_min, t_max)
        all_events = sorted(
            personal + team_gcal,
            key=lambda e: e["start"].get("dateTime", ""),
        )
        if not all_events:
            return "📋 해당 기간에 일정이 없습니다."
        return "📋 *일정 목록*\n\n" + calendar_service.format_event_list(all_events)

    elif tool == "list_team_events":
        t_min = _to_rfc3339(args["time_min"], end=False)
        t_max = _to_rfc3339(args["time_max"], end=True)
        team_events = db.get_team_events_by_range(t_min, t_max)
        if not team_events:
            return "📋 해당 기간에 팀 일정이 없습니다."
        PRIORITY_ICON = {"red": "🔴", "yellow": "🟡", "green": "🟢"}
        lines = ["📋 *팀 일정 목록*\n"]
        for e in team_events:
            icon      = PRIORITY_ICON.get(e["priority"], "🟡")
            start     = e["start_dt"][:16].replace("T", " ")
            end       = e["end_dt"][:16].replace("T", " ")
            organizer = e.get("organizer_name") or f"user_{e['organizer_id']}"
            lines.append(f"{icon} *{e['title']}*\n  📅 {start} ~ {end}\n  👤 {organizer}")
        return "\n\n".join(lines)

    elif tool == "delete_event":
        success = calendar_service.delete_event(
            uid, args["query"], args.get("date_hint")
        )
        if success:
            return f"🗑 *'{args['query']}'* 일정을 취소했습니다."
        return f"⚠️ *'{args['query']}'* 와 일치하는 일정을 찾지 못했습니다."

    elif tool == "find_free_slots":
        today_str = now.strftime("%Y-%m-%d")
        date_from = args.get("date_from", today_str)
        date_to   = args.get("date_to",   date_from)
        duration  = args.get("duration_hours", 1.0)
        slots_by_day = calendar_service.find_free_slots(uid, date_from, date_to, duration)
        if not slots_by_day:
            return f"⚠️ {date_from} ~ {date_to} 기간에 {duration}시간 연속으로 비는 시간대가 없습니다."
        lines = [f"⏱ *빈 시간대 ({duration}시간 이상)*\n"]
        for day, slots in sorted(slots_by_day.items()):
            lines.append(f"*{day}*")
            lines.extend(f"  • {s}" for s in slots)
        return "\n".join(lines)

    elif tool == "set_reminder":
        t_min   = now.isoformat()
        t_max   = (now + timedelta(weeks=2)).isoformat()
        events  = calendar_service.list_events(uid, t_min, t_max)
        query   = args.get("event_query", "").lower()
        matched = [e for e in events if query in e.get("summary", "").lower()]

        if not matched:
            return f"⚠️ *'{args['event_query']}'* 일정을 찾지 못했습니다."

        event = matched[0]
        start = event["start"].get("dateTime", "")
        mins  = args.get("minutes_before", DEFAULT_REMINDER_MINUTES)
        schedule_reminders_for_event(uid, event["id"], event.get("summary", ""), start, mins)

        mins_str = ", ".join(f"{m}분 전" for m in mins)
        return (
            f"✅ *리마인더 설정 완료*\n"
            f"📅 {event.get('summary')}\n"
            f"⏰ {mins_str} 알림 예정"
        )

    return "처리되지 않은 요청입니다."
