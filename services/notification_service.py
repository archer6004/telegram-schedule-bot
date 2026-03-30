"""
알림 전송 서비스
- 리마인더 메시지 포맷 및 전송
- 아침 브리핑 메시지 포맷 및 전송

scheduler_service.py는 '언제 보낼지(job scheduling)'만 담당하고,
실제 메시지 구성 및 전송 로직은 이 파일에서 처리합니다.
"""
import logging
from datetime import datetime

import pytz
from telegram import Bot

from config import TIMEZONE
from services.calendar_service import list_events, format_event_list
from services.weather_service import (
    get_today_summary, format_event_weather_hint,
)

logger = logging.getLogger(__name__)
tz = pytz.timezone(TIMEZONE)


# ── 포맷 헬퍼 ────────────────────────────────────────────

def _fmt_dt(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str).astimezone(tz)
        return dt.strftime("%Y년 %m월 %d일 (%a) %H:%M")
    except Exception:
        return iso_str


def _build_reminder_text(reminder: dict) -> str:
    return (
        f"⏰ *리마인더*\n"
        f"📅 *{reminder['event_title']}*\n"
        f"🕐 {_fmt_dt(reminder['event_datetime'])}"
    )


def _build_briefing_text(today: datetime, events: list) -> str:
    count      = len(events)
    date_label = today.strftime("%m/%d %a")
    weather    = get_today_summary()

    if count == 0:
        return (
            f"🌅 좋은 아침이에요!\n"
            f"{weather}\n\n"
            f"📋 오늘 ({date_label}) 일정이 없습니다. 여유로운 하루 되세요! 😊"
        )

    # 각 일정에 날씨 힌트 붙이기 (비/눈 등 주의 날씨만)
    event_lines = []
    for e in events:
        dt_str = e.get("start", {}).get("dateTime", "")
        hint   = format_event_weather_hint(dt_str) if dt_str else ""
        title  = e.get("summary", "(제목없음)")
        time_s = dt_str[11:16] if "T" in dt_str else "종일"
        line   = f"• {time_s} *{title}*"
        if hint:
            line += f"\n  {hint}"
        event_lines.append(line)

    emoji      = "💪" if count >= 3 else "😊"
    event_text = "\n".join(event_lines)
    return (
        f"🌅 좋은 아침이에요!\n"
        f"{weather}\n\n"
        f"📋 오늘 ({date_label}) 일정 *{count}건*\n\n"
        f"{event_text}\n\n"
        f"총 {count}건 · {emoji}"
    )


# ── 전송 함수 ────────────────────────────────────────────

async def send_reminder(bot: Bot, reminder: dict) -> None:
    """단일 리마인더를 사용자에게 전송합니다."""
    try:
        await bot.send_message(
            chat_id=reminder["telegram_id"],
            text=_build_reminder_text(reminder),
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.warning("리마인더 전송 실패 (id=%s): %s", reminder.get("id"), e)


async def send_morning_briefing(bot: Bot, user: dict) -> None:
    """단일 사용자에게 아침 브리핑을 전송합니다."""
    tid = user["telegram_id"]
    today = datetime.now(tz)
    t_min = today.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    t_max = today.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()

    try:
        events = list_events(tid, t_min, t_max)
        msg = _build_briefing_text(today, events)
        await bot.send_message(chat_id=tid, text=msg, parse_mode="Markdown")
    except Exception as e:
        logger.warning("아침 브리핑 전송 실패 (user=%s): %s", tid, e)
