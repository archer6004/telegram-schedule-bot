"""
사용자 관련 DB CRUD
"""
import json
from typing import Optional
from db.connection import db_conn


def upsert_user(telegram_id: int, username: str, full_name: str) -> None:
    with db_conn() as conn:
        conn.execute("""
            INSERT INTO users (telegram_id, username, full_name)
            VALUES (?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username  = excluded.username,
                full_name = excluded.full_name
        """, (telegram_id, username, full_name))


def update_user_registration(telegram_id: int, department: str, purpose: str) -> None:
    with db_conn() as conn:
        conn.execute("""
            UPDATE users SET department = ?, purpose = ?, status = 'PENDING'
            WHERE telegram_id = ?
        """, (department, purpose, telegram_id))


def get_user(telegram_id: int) -> Optional[dict]:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        return dict(row) if row else None


def get_all_users() -> list[dict]:
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_users_by_status(status: str) -> list[dict]:
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM users WHERE status = ?", (status,)
        ).fetchall()
        return [dict(r) for r in rows]


def approve_user(telegram_id: int, expires_at: Optional[str] = None) -> None:
    with db_conn() as conn:
        conn.execute("""
            UPDATE users
            SET status = 'APPROVED', approved_at = datetime('now'), expires_at = ?
            WHERE telegram_id = ?
        """, (expires_at, telegram_id))


def reject_user(telegram_id: int, reason: str = "") -> None:
    with db_conn() as conn:
        conn.execute("""
            UPDATE users SET status = 'REJECTED', rejected_reason = ?
            WHERE telegram_id = ?
        """, (reason, telegram_id))


def suspend_user(telegram_id: int) -> None:
    with db_conn() as conn:
        conn.execute(
            "UPDATE users SET status = 'SUSPENDED' WHERE telegram_id = ?", (telegram_id,)
        )


def delete_user(telegram_id: int) -> None:
    """
    사용자 및 모든 연관 데이터를 하나의 트랜잭션으로 삭제합니다.
    - reminders        : FOREIGN KEY ON DELETE CASCADE 로 자동 삭제
    - team_events      : organizer_id 일치하는 팀 이벤트 삭제
    - team_event_conflicts : 위 팀 이벤트의 충돌 기록 삭제
    - audit_log        : 해당 사용자 로그 삭제
    """
    with db_conn() as conn:
        # 1. 해당 사용자가 등록한 팀 이벤트의 참석자 기록 삭제
        conn.execute("""
            DELETE FROM team_event_attendees
            WHERE team_event_id IN (
                SELECT id FROM team_events WHERE organizer_id = ?
            )
        """, (telegram_id,))
        # 2. 해당 사용자가 참석자로 기록된 항목 삭제
        conn.execute(
            "DELETE FROM team_event_attendees WHERE user_id = ?", (telegram_id,)
        )
        # 3. 해당 사용자가 등록한 팀 이벤트의 충돌 기록 삭제
        conn.execute("""
            DELETE FROM team_event_conflicts
            WHERE team_event_id IN (
                SELECT id FROM team_events WHERE organizer_id = ?
            )
        """, (telegram_id,))
        # 4. 해당 사용자가 충돌 대상으로 기록된 항목 삭제
        conn.execute(
            "DELETE FROM team_event_conflicts WHERE conflicting_uid = ?", (telegram_id,)
        )
        # 5. 팀 이벤트 삭제
        conn.execute(
            "DELETE FROM team_events WHERE organizer_id = ?", (telegram_id,)
        )
        # 4. 감사 로그 삭제
        conn.execute(
            "DELETE FROM audit_log WHERE telegram_id = ?", (telegram_id,)
        )
        # 5. 사용자 삭제 (reminders는 ON DELETE CASCADE로 자동 삭제)
        conn.execute(
            "DELETE FROM users WHERE telegram_id = ?", (telegram_id,)
        )


def set_user_role(telegram_id: int, role: str) -> None:
    """role: 'OWNER' | 'ADMIN' | 'MEMBER'"""
    with db_conn() as conn:
        conn.execute(
            "UPDATE users SET role=? WHERE telegram_id=?", (role, telegram_id)
        )


def get_user_role(telegram_id: int) -> str:
    """DB에 저장된 역할 반환. 없으면 'MEMBER'."""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT role FROM users WHERE telegram_id=?", (telegram_id,)
        ).fetchone()
        return (row["role"] or "MEMBER") if row else "MEMBER"


def save_google_token(telegram_id: int, token_dict: dict) -> None:
    with db_conn() as conn:
        conn.execute(
            "UPDATE users SET google_token = ? WHERE telegram_id = ?",
            (json.dumps(token_dict), telegram_id),
        )


def get_google_token(telegram_id: int) -> Optional[dict]:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT google_token FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if row and row["google_token"]:
            return json.loads(row["google_token"])
        return None
