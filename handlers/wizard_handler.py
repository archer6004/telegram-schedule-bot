"""
인터랙티브 일정 등록 위저드
흐름: 제목 입력 → 날짜 선택 → 시간 선택 → 리마인더 토글 → 등록 완료

Idea sourced from workspace/telegram-chatbot:
- Inline button wizard flow (date quick-picks, time quick-picks)
- Toggle-style reminder checkboxes
- "당일 오전 8시" reminder type
"""
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import pytz

from config import TIMEZONE, DEFAULT_REMINDER_MINUTES
from constants import KEY_PENDING_TEAM_EVENT
import db as db
from services import calendar_service
from services.calendar_service import delete_event_by_id
from services.scheduler_service import schedule_reminders_for_event

tz = pytz.timezone(TIMEZONE)

# ── Wizard state keys (stored in ctx.user_data['wizard']['state']) ────────────
WIZ_TITLE         = "WIZ_TITLE"
WIZ_DATE_MANUAL   = "WIZ_DATE_MANUAL"
WIZ_TIME_MANUAL   = "WIZ_TIME_MANUAL"
WIZ_REMINDERS     = "WIZ_REMINDERS"
WIZ_MEMBER_SELECT = "WIZ_MEMBER_SELECT"


def _now() -> datetime:
    return datetime.now(tz)


# ── Entry point ───────────────────────────────────────────────────────────────

async def wizard_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """'📅 일정 등록' 버튼 또는 /add 명령어로 진입."""
    ctx.user_data['wizard'] = {'state': WIZ_TITLE, 'is_team': False}
    await update.message.reply_text(
        "✏️ 일정 *제목*을 입력해 주세요.\n예: 팀 미팅, 점심 약속",
        parse_mode="Markdown",
    )


async def cancel_wizard_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """'🗑 일정 취소' 버튼으로 진입 — 향후 2주 일정 목록을 버튼으로 표시."""
    uid = update.effective_user.id
    now = _now()
    t_min = now.isoformat()
    t_max = (now + timedelta(days=14)).isoformat()

    try:
        events = calendar_service.list_events(uid, t_min, t_max)
    except PermissionError:
        await update.message.reply_text(
            "⚠️ Google Calendar가 연동되지 않았습니다. /connect 를 입력해 주세요."
        )
        return

    # 종일 이벤트 포함, 최대 10개
    events = events[:10]
    if not events:
        await update.message.reply_text("📋 향후 2주 내 취소할 일정이 없습니다.")
        return

    ctx.user_data['cancel_wizard'] = {'events': events}
    await update.message.reply_text(
        "🗑 *취소할 일정을 선택해 주세요*\n_(향후 2주 일정)_",
        parse_mode="Markdown",
        reply_markup=_cancel_event_keyboard(events),
    )


def _cancel_event_keyboard(events: list) -> InlineKeyboardMarkup:
    buttons = []
    for i, e in enumerate(events):
        title = (e.get('summary') or '(제목없음)')[:18]
        dt = e.get('start', {})
        if 'dateTime' in dt:
            t = datetime.fromisoformat(dt['dateTime']).astimezone(tz).strftime('%m/%d %H:%M')
        else:
            t = (dt.get('date') or '')[:10]
        buttons.append([InlineKeyboardButton(
            f"🗑 {t}  {title}",
            callback_data=f"wiz_del_sel_{i}",
        )])
    buttons.append([InlineKeyboardButton("❌ 닫기", callback_data="wiz_del_abort")])
    return InlineKeyboardMarkup(buttons)


async def team_wizard_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """'👥 팀 일정 등록' 버튼으로 진입 — 마지막 단계에서 중요도 선택 추가."""
    ctx.user_data['wizard'] = {'state': WIZ_TITLE, 'is_team': True}
    await update.message.reply_text(
        "👥 팀 일정 *제목*을 입력해 주세요.\n예: 전체 회의, 스프린트 리뷰",
        parse_mode="Markdown",
    )


# ── Text-input dispatcher (called from calendar_handler.handle_message) ───────

async def wizard_handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    위저드가 활성 상태일 때 텍스트 입력을 처리합니다.
    메시지를 소비한 경우 True 반환 → handle_message에서 NLP 호출 건너뜁니다.
    """
    wizard = ctx.user_data.get('wizard')
    if not wizard:
        return False

    state = wizard.get('state')
    text  = update.message.text.strip()

    if state == WIZ_TITLE:
        wizard['title'] = text
        wizard['state'] = WIZ_DATE_MANUAL   # standby for manual date fallback
        await _ask_date(update, wizard)
        return True

    elif state == WIZ_DATE_MANUAL:
        wizard['date']  = text
        wizard['state'] = WIZ_TIME_MANUAL
        await _ask_time_msg(update, wizard)
        return True

    elif state == WIZ_TIME_MANUAL:
        wizard['time']  = text
        await _show_reminders_msg(update, wizard)
        return True

    return False


# ── Step screens ──────────────────────────────────────────────────────────────

async def _ask_date(update: Update, wizard: dict) -> None:
    now      = _now()
    today    = now.strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    keyboard = [
        [
            InlineKeyboardButton(f"오늘 ({now.strftime('%m/%d')})",
                                 callback_data=f"wiz_date_{today}"),
            InlineKeyboardButton(f"내일 ({(now + timedelta(days=1)).strftime('%m/%d')})",
                                 callback_data=f"wiz_date_{tomorrow}"),
        ],
        [InlineKeyboardButton("📝 직접 입력 (YYYY-MM-DD)", callback_data="wiz_date_manual")],
        [InlineKeyboardButton("❌ 취소", callback_data="wiz_cancel")],
    ]
    await update.message.reply_text(
        f"📅 *'{wizard['title']}'* 의 날짜를 선택해 주세요.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _ask_time_msg(update: Update, wizard: dict) -> None:
    """Message version of time selection (after manual date text input)."""
    await update.message.reply_text(
        f"⏰ *{wizard['date']}* 의 시간을 선택해 주세요.",
        parse_mode="Markdown",
        reply_markup=_time_keyboard(),
    )


async def _ask_time_query(query, wizard: dict) -> None:
    """Inline-edit version of time selection (after date button tap)."""
    await query.edit_message_text(
        f"⏰ *{wizard['date']}* 의 시간을 선택해 주세요.",
        parse_mode="Markdown",
        reply_markup=_time_keyboard(),
    )


def _time_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("09:00", callback_data="wiz_time_09:00"),
            InlineKeyboardButton("12:00", callback_data="wiz_time_12:00"),
            InlineKeyboardButton("14:00", callback_data="wiz_time_14:00"),
        ],
        [
            InlineKeyboardButton("17:00", callback_data="wiz_time_17:00"),
            InlineKeyboardButton("19:00", callback_data="wiz_time_19:00"),
            InlineKeyboardButton("21:00", callback_data="wiz_time_21:00"),
        ],
        [InlineKeyboardButton("📝 직접 입력 (HH:MM)", callback_data="wiz_time_manual")],
        [InlineKeyboardButton("❌ 취소", callback_data="wiz_cancel")],
    ])


def _reminder_keyboard(rems: set) -> InlineKeyboardMarkup:
    def btn(label: str, val: str) -> InlineKeyboardButton:
        mark = "✅ " if val in rems else ""
        return InlineKeyboardButton(f"{mark}{label}", callback_data=f"wiz_rem_{val}")

    return InlineKeyboardMarkup([
        [btn("10분 전", "10"),  btn("30분 전", "30")],
        [btn("1시간 전", "60"), btn("당일 오전 8시", "8am")],
        [
            InlineKeyboardButton("🚀 등록 완료", callback_data="wiz_rem_finish"),
            InlineKeyboardButton("❌ 취소",     callback_data="wiz_cancel"),
        ],
    ])


_REMINDER_TEXT = (
    "🔔 *알림 시점*을 선택해 주세요. (중복 선택 가능)\n"
    "선택하지 않으면 기본값(1시간·10분 전)으로 설정됩니다."
)


async def _show_reminders_query(query, wizard: dict) -> None:
    wizard['state'] = WIZ_REMINDERS
    rems = wizard.setdefault('reminders', set())
    await query.edit_message_text(
        _REMINDER_TEXT, parse_mode="Markdown",
        reply_markup=_reminder_keyboard(rems),
    )


async def _show_reminders_msg(update: Update, wizard: dict) -> None:
    wizard['state'] = WIZ_REMINDERS
    rems = wizard.setdefault('reminders', set())
    await update.message.reply_text(
        _REMINDER_TEXT, parse_mode="Markdown",
        reply_markup=_reminder_keyboard(rems),
    )


# ── Callback handler (registered in main.py with pattern="^wiz_") ─────────────

async def wizard_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    uid  = query.from_user.id

    # ── 일정 취소 위저드 ─────────────────────────────────────────────────────
    if data == "wiz_del_abort":
        ctx.user_data.pop('cancel_wizard', None)
        await query.edit_message_text("❌ 취소가 중단되었습니다.")
        return

    if data == "wiz_del_back":
        cw = ctx.user_data.get('cancel_wizard')
        if not cw:
            await query.edit_message_text("⚠️ 세션이 만료되었습니다. 다시 시작해 주세요.")
            return
        await query.edit_message_text(
            "🗑 *취소할 일정을 선택해 주세요*\n_(향후 2주 일정)_",
            parse_mode="Markdown",
            reply_markup=_cancel_event_keyboard(cw['events']),
        )
        return

    if data.startswith("wiz_del_sel_"):
        idx = int(data[len("wiz_del_sel_"):])
        cw = ctx.user_data.get('cancel_wizard')
        if not cw or idx >= len(cw['events']):
            await query.edit_message_text("⚠️ 세션이 만료되었습니다. 다시 시작해 주세요.")
            return
        e     = cw['events'][idx]
        title = e.get('summary') or '(제목없음)'
        dt    = e.get('start', {})
        if 'dateTime' in dt:
            t = datetime.fromisoformat(dt['dateTime']).astimezone(tz).strftime('%Y년 %m월 %d일 %H:%M')
        else:
            t = (dt.get('date') or '')[:10]
        await query.edit_message_text(
            f"🗑 *이 일정을 취소하시겠습니까?*\n\n"
            f"📌 {title}\n📅 {t}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ 취소 확인", callback_data=f"wiz_del_confirm_{idx}"),
                InlineKeyboardButton("◀ 목록으로",   callback_data="wiz_del_back"),
            ]]),
        )
        return

    if data.startswith("wiz_del_confirm_"):
        idx = int(data[len("wiz_del_confirm_"):])
        cw = ctx.user_data.get('cancel_wizard')
        if not cw or idx >= len(cw['events']):
            await query.edit_message_text("⚠️ 세션이 만료되었습니다. 다시 시작해 주세요.")
            return
        e        = cw['events'][idx]
        title    = e.get('summary') or '(제목없음)'
        event_id = e.get('id', '')
        try:
            delete_event_by_id(uid, event_id)
            await query.edit_message_text(
                f"✅ *'{title}'* 일정이 취소되었습니다.", parse_mode="Markdown"
            )
        except Exception as ex:
            await query.edit_message_text(f"❌ 취소 중 오류가 발생했습니다: {ex}")
        finally:
            ctx.user_data.pop('cancel_wizard', None)
        return

    # ── 일정 등록 위저드 취소 ────────────────────────────────────────────────
    if data == "wiz_cancel":
        ctx.user_data.pop('wizard', None)
        await query.edit_message_text("❌ 일정 등록이 취소되었습니다.")
        return

    # ── 팀원 선택: 완료 ──────────────────────────────────────────────────────
    if data == "wiz_member_done":
        wizard = ctx.user_data.get('wizard')
        if not wizard or wizard.get('state') != WIZ_MEMBER_SELECT:
            await query.edit_message_text("⚠️ 세션이 만료됐습니다. 다시 시작해 주세요.")
            return
        from handlers.team_handler import PRIORITY_BUTTONS
        invited_uids = list(wizard.get('invited_uids', set()))
        ctx.user_data[KEY_PENDING_TEAM_EVENT] = {
            "title":            wizard['title'],
            "start":            wizard['start_iso'],
            "end":              wizard['end_iso'],
            "location":         "",
            "description":      "",
            "attendees":        [],
            "reminder_minutes": wizard['minutes_list'],
            "invited_uids":     invited_uids,
        }
        rem_labels = wizard.get('rem_labels', ["기본값 (1시간·10분 전)"])
        ctx.user_data.pop('wizard', None)
        await query.edit_message_text(
            f"👥 *{wizard['title']}*\n"
            f"📅 {wizard['date']} {wizard['time']}\n"
            f"🔔 알림: {', '.join(rem_labels)}\n"
            f"👤 초대: {len(invited_uids)}명\n\n"
            f"팀 일정 *중요도*를 선택해 주세요.\n"
            f"_(충돌 발생 시 우선순위에 따라 자동 조율됩니다)_",
            parse_mode="Markdown",
            reply_markup=PRIORITY_BUTTONS,
        )
        return

    # ── 팀원 선택: 토글 ──────────────────────────────────────────────────────
    if data.startswith("wiz_member_"):
        wizard = ctx.user_data.get('wizard')
        if not wizard or wizard.get('state') != WIZ_MEMBER_SELECT:
            await query.edit_message_text("⚠️ 세션이 만료됐습니다. 다시 시작해 주세요.")
            return
        toggle_uid = int(data[len("wiz_member_"):])
        invited    = wizard.setdefault('invited_uids', set())
        if toggle_uid in invited:
            invited.discard(toggle_uid)
        else:
            invited.add(toggle_uid)
        await _show_member_select(query, uid, wizard)
        return

    wizard = ctx.user_data.get('wizard')
    if not wizard:
        await query.edit_message_text(
            "⚠️ 세션이 만료되었습니다. 📅 일정 등록을 다시 눌러주세요."
        )
        return

    # ── Date ────────────────────────────────────────────────────────────────
    if data == "wiz_date_manual":
        wizard['state'] = WIZ_DATE_MANUAL
        await query.edit_message_text("날짜를 직접 입력해 주세요. (형식: 2026-03-25)")
        return

    if data.startswith("wiz_date_"):
        wizard['date']  = data[len("wiz_date_"):]
        wizard['state'] = WIZ_TIME_MANUAL
        await _ask_time_query(query, wizard)
        return

    # ── Time ────────────────────────────────────────────────────────────────
    if data == "wiz_time_manual":
        wizard['state'] = WIZ_TIME_MANUAL
        await query.edit_message_text("시간을 직접 입력해 주세요. (형식: 14:30)")
        return

    if data.startswith("wiz_time_"):
        wizard['time']  = data[len("wiz_time_"):]
        await _show_reminders_query(query, wizard)
        return

    # ── Reminder toggle / finish ─────────────────────────────────────────────
    if data.startswith("wiz_rem_"):
        val = data[len("wiz_rem_"):]
        if val == "finish":
            await _finish_wizard(query, ctx, uid, wizard)
        else:
            rems = wizard.setdefault('reminders', set())
            if val in rems:
                rems.remove(val)
            else:
                rems.add(val)
            await _show_reminders_query(query, wizard)


# ── Finalize ─────────────────────────────────────────────────────────────────

async def _finish_wizard(query, ctx, uid: int, wizard: dict) -> None:
    try:
        title    = wizard['title']
        date     = wizard['date']
        time_str = wizard['time']
        rems     = wizard.get('reminders', set())

        start_iso = f"{date}T{time_str}:00+09:00"
        end_iso   = f"{date}T{_add_hour(time_str)}:00+09:00"

        # ── 팀 일정: 팀원 선택 화면으로 이동 ────────────────────────────
        if wizard.get('is_team'):
            minutes_list = _build_minutes(start_iso, rems)
            # ✅ 빈 리스트 체크: 반드시 list[int] 형태 보증
            minutes_list = minutes_list if (minutes_list and isinstance(minutes_list, list)) else DEFAULT_REMINDER_MINUTES
            # 다시 한 번 검증: DEFAULT_REMINDER_MINUTES도 list[int] 타입 확인
            if not isinstance(minutes_list, list):
                minutes_list = DEFAULT_REMINDER_MINUTES

            rem_labels   = _reminder_labels(rems) or ["기본값 (1시간·10분 전)"]
            # wizard에 이벤트 정보 저장 (팀원 선택 후 KEY_PENDING_TEAM_EVENT로 이동)
            wizard['start_iso']    = start_iso
            wizard['end_iso']      = end_iso
            wizard['minutes_list'] = minutes_list  # ✅ 반드시 list[int]
            wizard['rem_labels']   = rem_labels
            wizard['state']        = WIZ_MEMBER_SELECT
            wizard.setdefault('invited_uids', set())
            await _show_member_select(query, uid, wizard)
            return  # wizard는 아직 유지

        # ── 개인 일정: 바로 등록 ─────────────────────────────────────────
        event = calendar_service.create_event(
            uid, title=title, start=start_iso, end=end_iso
        )

        minutes_list = _build_minutes(start_iso, rems)
        # ✅ 빈 리스트 체크: 반드시 list[int] 형태 보증
        minutes_list = minutes_list if (minutes_list and isinstance(minutes_list, list)) else DEFAULT_REMINDER_MINUTES
        if not isinstance(minutes_list, list):
            minutes_list = DEFAULT_REMINDER_MINUTES

        schedule_reminders_for_event(
            uid, event["id"], title, start_iso,
            minutes_list,  # ✅ 반드시 list[int]
        )

        rem_labels = _reminder_labels(rems) or ["기본값 (1시간·10분 전)"]
        msg = (
            f"✅ *일정 등록 완료!*\n\n"
            f"📌 제목: {title}\n"
            f"📅 일시: {date} {time_str}\n"
            f"🔔 알림: {', '.join(rem_labels)}"
        )
        await query.edit_message_text(msg, parse_mode="Markdown")

    except PermissionError:
        await query.edit_message_text(
            "⚠️ Google Calendar가 연동되지 않았습니다. /connect 를 입력해 주세요."
        )
    except Exception as e:
        await query.edit_message_text(f"❌ 등록 중 오류가 발생했습니다: {e}")
    finally:
        ctx.user_data.pop('wizard', None)


# ── 팀원 선택 ─────────────────────────────────────────────────────────────────

async def _show_member_select(query, organizer_uid: int, wizard: dict) -> None:
    """팀원 선택 화면 (토글 방식)."""
    all_users = db.get_all_users()
    approved  = [u for u in all_users
                 if u.get('status') == 'APPROVED' and u['telegram_id'] != organizer_uid]
    invited   = wizard.get('invited_uids', set())

    buttons = []
    for u in approved:
        mark = "✅ " if u['telegram_id'] in invited else "👤 "
        name = u.get('full_name') or str(u['telegram_id'])
        dept = f" ({u['department']})" if u.get('department') else ""
        buttons.append([InlineKeyboardButton(
            f"{mark}{name}{dept}",
            callback_data=f"wiz_member_{u['telegram_id']}",
        )])

    n = len(invited)
    next_label = f"➡️ 다음 ({n}명 선택)" if n > 0 else "➡️ 다음 (선택 없이 진행)"
    buttons.append([InlineKeyboardButton(next_label, callback_data="wiz_member_done")])
    buttons.append([InlineKeyboardButton("❌ 취소", callback_data="wiz_cancel")])

    title = wizard.get('title', '')
    date  = wizard.get('date', '')
    time  = wizard.get('time', '')
    await query.edit_message_text(
        f"👥 *함께할 팀원을 선택해 주세요*\n"
        f"_{title} / {date} {time}_\n\n"
        f"선택하지 않으면 참석 알림 없이 등록됩니다.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _add_hour(time_str: str) -> str:
    """'14:30' → '15:30'"""
    h, m = map(int, time_str.split(':'))
    return f"{(h + 1) % 24:02d}:{m:02d}"


def _build_minutes(start_iso: str, rems: set) -> list[int]:
    """Convert selected reminder tokens to list of minutes-before-event."""
    minutes = []
    for r in rems:
        if r == "8am":
            try:
                event_dt = datetime.fromisoformat(start_iso).astimezone(tz)
                day_8am  = event_dt.replace(hour=8, minute=0, second=0, microsecond=0)
                delta    = int((event_dt - day_8am).total_seconds() / 60)
                if delta > 0:
                    minutes.append(delta)
            except Exception:
                pass
        else:
            try:
                minutes.append(int(r))
            except ValueError:
                pass
    return minutes


def _reminder_labels(rems: set) -> list[str]:
    labels = []
    for r in rems:
        if r == "8am":
            labels.append("당일 오전 8시")
        else:
            m = int(r)
            labels.append(f"{m}분 전" if m < 60 else f"{m // 60}시간 전")
    return labels
