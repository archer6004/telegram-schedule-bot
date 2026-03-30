"""
db 패키지 — 하위 repo 모듈을 한 곳에서 re-export합니다.
기존 `import database as db` 패턴을 `from db import ...` 로 대체할 수 있습니다.
"""
from db.connection  import get_conn, init_db
from db.user_repo   import (
    upsert_user, update_user_registration,
    get_user, get_users_by_status, get_all_users,
    approve_user, reject_user, suspend_user, delete_user,
    save_google_token, get_google_token,
    set_user_role, get_user_role,
)
from db.settings_repo import get_setting, set_setting
from db.team_repo import (
    create_team_event, create_team_event_with_google_id,
    update_team_event_google_id, get_team_event,
    add_conflict, get_conflicts, resolve_conflict,
    get_pending_conflicts_for_user, get_all_connected_users,
    get_overlapping_team_events, get_team_events_by_range,
    add_attendee, update_attendee_status, get_attendees,
    get_pending_attendance_for_user,
)
from db.reminder_repo import (
    add_reminder, get_pending_reminders,
    mark_reminder_sent, get_reminders_for_event,
    delete_past_sent_reminders,
    delete_old_audit_logs, delete_old_resolved_conflicts,
    log_action, get_stats,
)

__all__ = [
    "get_conn", "init_db",
    "upsert_user", "update_user_registration",
    "get_user", "get_users_by_status", "get_all_users",
    "approve_user", "reject_user", "suspend_user", "delete_user",
    "save_google_token", "get_google_token",
    "set_user_role", "get_user_role",
    "get_setting", "set_setting",
    "create_team_event", "create_team_event_with_google_id",
    "update_team_event_google_id", "get_team_event",
    "add_conflict", "get_conflicts", "resolve_conflict",
    "get_pending_conflicts_for_user", "get_all_connected_users",
    "get_overlapping_team_events", "get_team_events_by_range",
    "add_attendee", "update_attendee_status", "get_attendees",
    "get_pending_attendance_for_user",
    "add_reminder", "get_pending_reminders",
    "mark_reminder_sent", "get_reminders_for_event",
    "delete_past_sent_reminders",
    "delete_old_audit_logs", "delete_old_resolved_conflicts",
    "log_action", "get_stats",
]
