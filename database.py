"""
database.py — 하위 호환 shim
새 코드는 db.user_repo / db.reminder_repo 를 직접 import하세요.
기존 `import database as db` 패턴은 계속 동작합니다.
"""
from db.connection import get_conn, init_db          # noqa: F401
from db.user_repo import (                           # noqa: F401
    upsert_user, update_user_registration,
    get_user, get_users_by_status,
    approve_user, reject_user, suspend_user,
    save_google_token, get_google_token,
)
from db.reminder_repo import (                       # noqa: F401
    add_reminder, get_pending_reminders,
    mark_reminder_sent, get_reminders_for_event,
    log_action, get_stats,
)
