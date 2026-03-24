"""
사용자 관련 DB CRUD
"""
import json
from typing import Optional
from db.connection import get_conn


def upsert_user(telegram_id: int, username: str, full_name: str) -> None:
    conn = get_conn()
    conn.execute("""
        INSERT INTO users (telegram_id, username, full_name)
        VALUES (?, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET
            username  = excluded.username,
            full_name = excluded.full_name
    """, (telegram_id, username, full_name))
    conn.commit()
    conn.close()


def update_user_registration(telegram_id: int, department: str, purpose: str) -> None:
    conn = get_conn()
    conn.execute("""
        UPDATE users SET department = ?, purpose = ?, status = 'PENDING'
        WHERE telegram_id = ?
    """, (department, purpose, telegram_id))
    conn.commit()
    conn.close()


def get_user(telegram_id: int) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_users_by_status(status: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM users WHERE status = ?", (status,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def approve_user(telegram_id: int, expires_at: Optional[str] = None) -> None:
    conn = get_conn()
    conn.execute("""
        UPDATE users
        SET status = 'APPROVED', approved_at = datetime('now'), expires_at = ?
        WHERE telegram_id = ?
    """, (expires_at, telegram_id))
    conn.commit()
    conn.close()


def reject_user(telegram_id: int, reason: str = "") -> None:
    conn = get_conn()
    conn.execute("""
        UPDATE users SET status = 'REJECTED', rejected_reason = ?
        WHERE telegram_id = ?
    """, (reason, telegram_id))
    conn.commit()
    conn.close()


def suspend_user(telegram_id: int) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE users SET status = 'SUSPENDED' WHERE telegram_id = ?", (telegram_id,)
    )
    conn.commit()
    conn.close()


def save_google_token(telegram_id: int, token_dict: dict) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE users SET google_token = ? WHERE telegram_id = ?",
        (json.dumps(token_dict), telegram_id),
    )
    conn.commit()
    conn.close()


def get_google_token(telegram_id: int) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute(
        "SELECT google_token FROM users WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()
    conn.close()
    if row and row["google_token"]:
        return json.loads(row["google_token"])
    return None
