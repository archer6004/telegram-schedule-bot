"""
리마인더 / 감사 로그 관련 DB CRUD
"""
from db.connection import get_conn


# ── 리마인더 ──────────────────────────────────────────────

def add_reminder(telegram_id: int, event_id: str, event_title: str,
                 event_datetime: str, remind_at: str) -> None:
    conn = get_conn()
    conn.execute("""
        INSERT INTO reminders (telegram_id, event_id, event_title, event_datetime, remind_at)
        VALUES (?, ?, ?, ?, ?)
    """, (telegram_id, event_id, event_title, event_datetime, remind_at))
    conn.commit()
    conn.close()


def get_pending_reminders(before: str) -> list[dict]:
    """remind_at이 before 이전이고 아직 전송 안 된 리마인더를 반환합니다."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM reminders
        WHERE sent = 0 AND remind_at <= ?
    """, (before,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_reminder_sent(reminder_id: int) -> None:
    conn = get_conn()
    conn.execute("UPDATE reminders SET sent = 1 WHERE id = ?", (reminder_id,))
    conn.commit()
    conn.close()


def get_reminders_for_event(telegram_id: int, event_id: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM reminders WHERE telegram_id = ? AND event_id = ? AND sent = 0
    """, (telegram_id, event_id)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_past_sent_reminders(before_date: str) -> int:
    """
    전송 완료된(sent=1) 오래된 리마인더 행을 삭제합니다.
    before_date: ISO8601 날짜 문자열 (예: '2026-03-01')
    반환값: 삭제된 행 수
    Idea from workspace/telegram-chatbot auto-cleanup job.
    """
    conn = get_conn()
    cur = conn.execute(
        "DELETE FROM reminders WHERE sent = 1 AND remind_at < ?", (before_date,)
    )
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted


# ── 감사 로그 ─────────────────────────────────────────────

def log_action(telegram_id: int, action: str, detail: str = "") -> None:
    conn = get_conn()
    conn.execute("""
        INSERT INTO audit_log (telegram_id, action, detail) VALUES (?, ?, ?)
    """, (telegram_id, action, detail))
    conn.commit()
    conn.close()


def get_stats() -> dict:
    conn = get_conn()
    pending = conn.execute(
        "SELECT COUNT(*) FROM users WHERE status='PENDING'"
    ).fetchone()[0]
    approved = conn.execute(
        "SELECT COUNT(*) FROM users WHERE status='APPROVED'"
    ).fetchone()[0]
    today_actions = conn.execute("""
        SELECT COUNT(*) FROM audit_log WHERE date(created_at) = date('now')
    """).fetchone()[0]
    conn.close()
    return {"pending": pending, "approved": approved, "today_actions": today_actions}
