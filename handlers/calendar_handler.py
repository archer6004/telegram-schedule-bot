"""
캘린더 슬래시 커맨드 핸들러
/today  /week  /add  /free  /cancel  /remind  /help
그 외 자연어 메시지 → Claude API → 캘린더 액션
"""
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes
import pytz

import db as db
from config import TIMEZONE, DEFAULT_REMINDER_MINUTES
from models.user import UserStatus
from services import claude_service, calendar_service
from services.scheduler_service import schedule_reminders_for_event
from handlers.wizard_handler import wizard_start, wizard_handle_text

tz = pytz.timezone(TIMEZONE)


def _approved(telegram_id: int) -> bool:
    record = db.get_user(telegram_id)
    return record is not None and record.get("status") == UserStatus.APPROVED


def _now() -> datetime:
    return datetime.now(tz)


# ── 하단 고정 메뉴 (ReplyKeyboardMarkup) ──────────────────

def get_main_menu() -> ReplyKeyboardMarkup:
    """
    승인된 사용자에게 항상 표시되는 하단 고정 메뉴.
    Idea from workspace/telegram-chatbot persistent keyboard.
    """
    keyboard = [
        [KeyboardButton("📅 일정 등록"), KeyboardButton("📋 오늘 일정")],
        [KeyboardButton("📋 이번 주 일정"), KeyboardButton("⏱ 빈 시간 찾기")],
        [KeyboardButton("❓ 도움말")],
    ]
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        input_field_placeholder="메뉴를 선택하거나 자연어로 입력하세요",
    )


# ── /help ────────────────────────────────────────────────

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *스케줄 챗봇 사용법*\n\n"
        "*하단 메뉴 버튼*\n"
        "📅 일정 등록 — 단계별 위저드로 일정 추가\n"
        "📋 오늘 일정 — 오늘 일정 조회\n"
        "📋 이번 주 일정 — 이번 주 일정 조회\n"
        "⏱ 빈 시간 찾기 — 오늘 빈 시간대\n\n"
        "*슬래시 커맨드*\n"
        "/today — 오늘 일정\n"
        "/week — 이번 주 일정\n"
        "/free — 오늘 빈 시간\n"
        "/connect — Google Calendar 연동\n"
        "/status — 내 권한 상태\n\n"
        "*자연어 명령 예시*\n"
        "• 내일 오후 3시에 팀 미팅 잡아줘\n"
        "• 이번 주 일정 보여줘\n"
        "• 금요일 회의 취소해줘\n"
        "• 다음 주 2시간 비는 시간 찾아줘\n"
        "• 팀 미팅 1시간 전에 알려줘",
        parse_mode="Markdown",
        reply_markup=get_main_menu(),
    )


# ── /today ───────────────────────────────────────────────

async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _approved(uid):
        await update.message.reply_text("❌ 승인된 사용자만 이용 가능합니다. /start")
        return

    now   = _now()
    t_min = now.replace(hour=0,  minute=0,  second=0,  microsecond=0).isoformat()
    t_max = now.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()

    try:
        events = calendar_service.list_events(uid, t_min, t_max)
    except PermissionError as e:
        await update.message.reply_text(str(e), reply_markup=get_main_menu())
        return

    if not events:
        text = f"📋 오늘 ({now.strftime('%m/%d %a')}) 일정이 없습니다."
    else:
        lines = [f"📋 *오늘 일정* ({now.strftime('%m/%d %a')})\n"]
        lines.append(calendar_service.format_event_list(events))
        text = "\n".join(lines)

    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=get_main_menu())


# ── /week ────────────────────────────────────────────────

async def cmd_week(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _approved(uid):
        await update.message.reply_text("❌ 승인된 사용자만 이용 가능합니다. /start")
        return

    now        = _now()
    week_start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    week_end   = (week_start + timedelta(days=6)).replace(hour=23, minute=59, second=59)

    try:
        events = calendar_service.list_events(uid, week_start.isoformat(), week_end.isoformat())
    except PermissionError as e:
        await update.message.reply_text(str(e), reply_markup=get_main_menu())
        return

    if not events:
        text = f"📋 이번 주 ({week_start.strftime('%m/%d')} ~ {week_end.strftime('%m/%d')}) 일정이 없습니다."
    else:
        lines = [f"📋 *이번 주 일정* ({week_start.strftime('%m/%d')} ~ {week_end.strftime('%m/%d')})\n"]
        lines.append(calendar_service.format_event_list(events))
        text = "\n".join(lines)

    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=get_main_menu())


# ── /free ────────────────────────────────────────────────

async def cmd_free(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _approved(uid):
        await update.message.reply_text("❌ 승인된 사용자만 이용 가능합니다. /start")
        return

    today = _now().strftime("%Y-%m-%d")
    try:
        slots = calendar_service.find_free_slots(uid, today, duration_hours=1.0)
    except PermissionError as e:
        await update.message.reply_text(str(e), reply_markup=get_main_menu())
        return

    if not slots:
        text = "오늘은 비는 시간이 없습니다. 😅"
    else:
        lines = ["⏱ *오늘 비는 시간대*\n"] + [f"• {s}" for s in slots]
        text = "\n".join(lines)

    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=get_main_menu())


# ── 자연어 메시지 처리 + 하단 메뉴 버튼 처리 ──────────────

# 하단 메뉴 버튼 텍스트 목록 (NLP로 넘기지 않고 직접 처리)
_MENU_BUTTONS = {"📅 일정 등록", "📋 오늘 일정", "📋 이번 주 일정", "⏱ 빈 시간 찾기", "❓ 도움말"}


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
    if user_text == "📋 오늘 일정":
        await cmd_today(update, ctx)
        return
    if user_text == "📋 이번 주 일정":
        await cmd_week(update, ctx)
        return
    if user_text == "⏱ 빈 시간 찾기":
        await cmd_free(update, ctx)
        return
    if user_text == "❓ 도움말":
        await cmd_help(update, ctx)
        return

    # 3. 자연어 → Claude API
    await update.message.chat.send_action("typing")
    history = ctx.user_data.get("history", [])

    try:
        intent = await claude_service.parse_intent(user_text, history)
    except Exception as e:
        await update.message.reply_text(
            f"⚠️ Claude API 오류: {e}", reply_markup=get_main_menu()
        )
        return

    history.append({"role": "user", "content": user_text})
    ctx.user_data["history"] = history[-12:]

    tool = intent["tool"]
    args = intent["args"]

    try:
        reply = await _dispatch(uid, tool, args, ctx)
    except PermissionError:
        reply = "⚠️ Google Calendar가 연동되지 않았습니다. /connect 를 입력해 주세요."
    except Exception as e:
        reply = f"⚠️ 처리 중 오류가 발생했습니다: {e}"

    await update.message.reply_text(
        reply, parse_mode="Markdown",
        disable_web_page_preview=True,
        reply_markup=get_main_menu(),
    )


async def _dispatch(uid: int, tool: str, args: dict, ctx) -> str:
    now = _now()

    if tool == "plain_reply":
        return args.get("message", "")

    elif tool == "create_event":
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
        events = calendar_service.list_events(uid, args["time_min"], args["time_max"])
        if not events:
            return "📋 해당 기간에 일정이 없습니다."
        return "📋 *일정 목록*\n\n" + calendar_service.format_event_list(events)

    elif tool == "delete_event":
        success = calendar_service.delete_event(
            uid, args["query"], args.get("date_hint")
        )
        if success:
            return f"🗑 *'{args['query']}'* 일정을 취소했습니다."
        return f"⚠️ *'{args['query']}'* 와 일치하는 일정을 찾지 못했습니다."

    elif tool == "find_free_slots":
        date     = args.get("date", now.strftime("%Y-%m-%d"))
        duration = args.get("duration_hours", 1.0)
        slots    = calendar_service.find_free_slots(uid, date, duration)
        if not slots:
            return f"⚠️ {date} 에 {duration}시간 비는 시간대가 없습니다."
        lines = [f"⏱ *{date} 빈 시간대*\n"] + [f"• {s}" for s in slots]
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
