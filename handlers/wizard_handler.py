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
import db as db
from services import calendar_service
from services.scheduler_service import schedule_reminders_for_event

tz = pytz.timezone(TIMEZONE)

# ── Wizard state keys (stored in ctx.user_data['wizard']['state']) ────────────
WIZ_TITLE       = "WIZ_TITLE"
WIZ_DATE_MANUAL = "WIZ_DATE_MANUAL"
WIZ_TIME_MANUAL = "WIZ_TIME_MANUAL"
WIZ_REMINDERS   = "WIZ_REMINDERS"


def _now() -> datetime:
    return datetime.now(tz)


# ── Entry point ───────────────────────────────────────────────────────────────

async def wizard_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """'📅 일정 등록' 버튼 또는 /add 명령어로 진입."""
    ctx.user_data['wizard'] = {'state': WIZ_TITLE}
    await update.message.reply_text(
        "✏️ 일정 *제목*을 입력해 주세요.\n예: 팀 미팅, 점심 약속",
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

    # ── Cancel ──────────────────────────────────────────────────────────────
    if data == "wiz_cancel":
        ctx.user_data.pop('wizard', None)
        await query.edit_message_text("❌ 일정 등록이 취소되었습니다.")
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

        event = calendar_service.create_event(
            uid, title=title, start=start_iso, end=end_iso
        )

        # Build minutes list from selected reminder options
        minutes_list = _build_minutes(start_iso, rems)
        schedule_reminders_for_event(
            uid, event["id"], title, start_iso,
            minutes_list if minutes_list else DEFAULT_REMINDER_MINUTES,
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
