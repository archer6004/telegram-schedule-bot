"""
스케줄러 서비스 — '언제' 실행할지 담당
메시지 구성 및 전송은 notification_service 에 위임합니다.
"""
import logging
from datetime import datetime, timedelta

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import TIMEZONE, DEFAULT_REMINDER_MINUTES
import db as repo
from services.notification_service import send_reminder, send_morning_briefing
from services.backup_service import run_backup

logger = logging.getLogger(__name__)
tz = pytz.timezone(TIMEZONE)
scheduler = AsyncIOScheduler(timezone=tz)

# 봇 인스턴스 (main.py에서 주입)
_bot = None


def init_scheduler(bot) -> None:
    global _bot
    _bot = bot

    # 1분마다 리마인더 체크
    scheduler.add_job(check_reminders, "interval", minutes=1, id="reminder_check")

    # 매일 오전 8시 브리핑
    scheduler.add_job(
        morning_briefing,
        CronTrigger(hour=8, minute=0, timezone=tz),
        id="morning_briefing",
    )

    # 10분마다 전송 완료된 오래된 리마인더 정리 (DB bloat 방지)
    scheduler.add_job(cleanup_old_reminders, "interval", minutes=10, id="reminder_cleanup")

    # 매일 새벽 2시 DB 백업 (Google Drive 백업 폴더, 7일 보관)
    scheduler.add_job(
        run_daily_backup,
        CronTrigger(hour=2, minute=0, timezone=tz),
        id="db_backup",
    )

    # 매일 새벽 3시 오래된 데이터 정리
    scheduler.add_job(
        cleanup_old_data,
        CronTrigger(hour=3, minute=0, timezone=tz),
        id="data_cleanup",
    )

    scheduler.start()
    logger.info("APScheduler 시작 완료")


async def check_reminders() -> None:
    now_str = datetime.now(tz).isoformat()
    pending = repo.get_pending_reminders(before=now_str)
    for reminder in pending:
        await send_reminder(_bot, reminder)
        repo.mark_reminder_sent(reminder["id"])


async def morning_briefing() -> None:
    approved_users = repo.get_users_by_status("APPROVED")
    for user in approved_users:
        await send_morning_briefing(_bot, user)


async def run_daily_backup() -> None:
    """매일 새벽 2시 DB 백업 실행."""
    try:
        path = run_backup()
        if path:
            logger.info("DB 백업 완료 → %s", path)
    except Exception as e:
        logger.error("DB 백업 실패: %s", e)


async def cleanup_old_reminders() -> None:
    """전송 완료된 리마인더 중 30일 이상 지난 항목을 삭제합니다."""
    cutoff = (datetime.now(tz) - timedelta(days=30)).isoformat()
    deleted = repo.delete_past_sent_reminders(cutoff)
    if deleted:
        logger.info("오래된 리마인더 %d건 정리 완료", deleted)


async def cleanup_old_data() -> None:
    """매일 새벽 3시 — 오래된 로그/충돌 기록 자동 삭제."""
    now = datetime.now(tz)

    # 리마인더: sent=1, 30일 경과
    r_cutoff = (now - timedelta(days=30)).isoformat()
    r = repo.delete_past_sent_reminders(r_cutoff)

    # 감사 로그: 90일 경과
    a_cutoff = (now - timedelta(days=90)).isoformat()
    a = repo.delete_old_audit_logs(a_cutoff)

    # 충돌 기록: resolved, 60일 경과
    c_cutoff = (now - timedelta(days=60)).isoformat()
    c = repo.delete_old_resolved_conflicts(c_cutoff)

    total = r + a + c
    if total:
        logger.info("일일 데이터 정리 완료 — 리마인더 %d, 로그 %d, 충돌기록 %d건 삭제", r, a, c)


def schedule_reminders_for_event(
    telegram_id: int,
    event_id: str,
    event_title: str,
    event_datetime_str: str,
    minutes_before: list[int],
) -> None:
    """일정 생성 후 리마인더를 DB에 등록합니다."""
    # ✅ 방어적 코딩: minutes_before가 list[int]인지 검증
    if not isinstance(minutes_before, list):
        logger.warning(
            "❌ 리마인더 등록 실패: minutes_before는 list[int]여야 합니다 (받은 타입: %s)",
            type(minutes_before).__name__
        )
        # 기본값으로 대체
        from config import DEFAULT_REMINDER_MINUTES
        minutes_before = DEFAULT_REMINDER_MINUTES

    # 리스트의 모든 요소가 int인지 검증
    try:
        minutes_before = [int(m) for m in minutes_before]
    except (TypeError, ValueError) as e:
        logger.warning(
            "❌ 리마인더 등록 실패: minutes_before의 요소가 정수가 아닙니다: %s",
            e
        )
        from config import DEFAULT_REMINDER_MINUTES
        minutes_before = DEFAULT_REMINDER_MINUTES

    try:
        event_dt = datetime.fromisoformat(event_datetime_str).astimezone(tz)
    except Exception as e:
        logger.warning("리마인더 등록 실패 — 날짜 파싱 오류: %s", e)
        return

    now = datetime.now(tz)
    for mins in minutes_before:
        remind_at = event_dt - timedelta(minutes=mins)
        if remind_at > now:
            repo.add_reminder(
                telegram_id=telegram_id,
                event_id=event_id,
                event_title=event_title,
                event_datetime=event_dt.isoformat(),
                remind_at=remind_at.isoformat(),
            )
