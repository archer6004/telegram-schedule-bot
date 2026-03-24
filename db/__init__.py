"""
db 패키지 — 하위 repo 모듈을 한 곳에서 re-export합니다.
기존 `import database as db` 패턴을 `from db import ...` 로 대체할 수 있습니다.
"""
from db.connection  import get_conn, init_db
from db.user_repo   import (
    upsert_user, update_user_registration,
    get_user, get_users_by_status,
    approve_user, reject_user, suspend_user,
    save_google_token, get_google_token,
)
from db.reminder_repo import (
    add_reminder, get_pending_reminders,
    mark_reminder_sent, get_reminders_for_event,
    delete_past_sent_reminders,
    log_action, get_stats,
)

__all__ = [
    "get_conn", "init_db",
    "upsert_user", "update_user_registration",
    "get_user", "get_users_by_status",
    "approve_user", "reject_user", "suspend_user",
    "save_google_token", "get_google_token",
    "add_reminder", "get_pending_reminders",
    "mark_reminder_sent", "get_reminders_for_event",
    "delete_past_sent_reminders",
    "log_action", "get_stats",
]
