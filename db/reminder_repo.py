"""
리마인더 / 감사 로그 관련 DB CRUD
"""
from db.connection import db_conn


# ── 리마인더 ──────────────────────────────────────────────

def add_reminder(telegram_id: int, event_id: str, event_title: str,
                 event_datetime: str, remind_at: str) -> None:
    with db_conn() as conn:
        conn.execute("""
            INSERT INTO reminders (telegram_id, event_id, event_title, event_datetime, remind_at)
            VALUES (?, ?, ?, ?, ?)
        """, (telegram_id, event_id, event_title, event_datetime, remind_at))


def get_pending_reminders(before: str) -> list[dict]:
    """remind_at이 before 이전이고 아직 전송 안 된 리마인더를 반환합니다."""
    with db_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM reminders
            WHERE sent = 0 AND remind_at <= ?
        """, (before,)).fetchall()
        return [dict(r) for r in rows]


def mark_reminder_sent(reminder_id: int) -> None:
    with db_conn() as conn:
        conn.execute("UPDATE reminders SET sent = 1 WHERE id = ?", (reminder_id,))


def get_reminders_for_event(telegram_id: int, event_id: str) -> list[dict]:
    with db_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM reminders WHERE telegram_id = ? AND event_id = ? AND sent = 0
        """, (telegram_id, event_id)).fetchall()
        return [dict(r) for r in rows]


def delete_past_sent_reminders(before_date: str) -> int:
    """전송 완료된(sent=1) 오래된 리마인더 행을 삭제합니다."""
    with db_conn() as conn:
        cur = conn.execute(
            "DELETE FROM reminders WHERE sent = 1 AND remind_at < ?", (before_date,)
        )
        return cur.rowcount


# ── 정리 (자동삭제) ───────────────────────────────────────

def delete_old_audit_logs(before_date: str) -> int:
    """90일 이상 지난 감사 로그를 삭제합니다."""
    with db_conn() as conn:
        cur = conn.execute(
            "DELETE FROM audit_log WHERE created_at < ?", (before_date,)
        )
        return cur.rowcount


def delete_old_resolved_conflicts(before_date: str) -> int:
    """60일 이상 지난 해결된 충돌 기록을 삭제합니다."""
    with db_conn() as conn:
        cur = conn.execute(
            "DELETE FROM team_event_conflicts WHERE resolution != 'pending' AND created_at < ?",
            (before_date,)
        )
        return cur.rowcount


# ── 감사 로그 ─────────────────────────────────────────────

def log_action(telegram_id: int, action: str, detail: str = "") -> None:
    with db_conn() as conn:
        conn.execute("""
            INSERT INTO audit_log (telegram_id, action, detail) VALUES (?, ?, ?)
        """, (telegram_id, action, detail))


def get_stats() -> dict:
    with db_conn() as conn:
        pending = conn.execute(
            "SELECT COUNT(*) FROM users WHERE status='PENDING'"
        ).fetchone()[0]
        approved = conn.execute(
            "SELECT COUNT(*) FROM users WHERE status='APPROVED'"
        ).fetchone()[0]
        today_actions = conn.execute("""
            SELECT COUNT(*) FROM audit_log WHERE date(created_at) = date('now')
        """).fetchone()[0]
        return {"pending": pending, "approved": approved, "today_actions": today_actions}
