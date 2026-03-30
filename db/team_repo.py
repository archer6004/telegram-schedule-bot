"""팀 이벤트 DB 레포지토리"""
from db.connection import db_conn


def create_team_event(title: str, start_dt: str, end_dt: str,
                      organizer_id: int, priority: str) -> int:
    with db_conn() as conn:
        cur = conn.execute(
            "INSERT INTO team_events (title, start_dt, end_dt, organizer_id, priority) "
            "VALUES (?, ?, ?, ?, ?)",
            (title, start_dt, end_dt, organizer_id, priority),
        )
        return cur.lastrowid


def create_team_event_with_google_id(
    title: str, start_dt: str, end_dt: str,
    organizer_id: int, priority: str, google_event_id: str,
) -> int:
    """팀 이벤트 INSERT + google_event_id UPDATE를 하나의 트랜잭션으로 처리."""
    with db_conn() as conn:
        cur = conn.execute(
            "INSERT INTO team_events (title, start_dt, end_dt, organizer_id, priority, google_event_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (title, start_dt, end_dt, organizer_id, priority, google_event_id),
        )
        return cur.lastrowid


def update_team_event_google_id(event_id: int, google_event_id: str) -> None:
    with db_conn() as conn:
        conn.execute(
            "UPDATE team_events SET google_event_id=? WHERE id=?",
            (google_event_id, event_id),
        )


def get_team_event(event_id: int) -> dict | None:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM team_events WHERE id=?", (event_id,)
        ).fetchone()
        return dict(row) if row else None


def add_conflict(team_event_id: int, conflicting_uid: int,
                 their_priority: str = "yellow") -> int:
    with db_conn() as conn:
        cur = conn.execute(
            "INSERT INTO team_event_conflicts "
            "(team_event_id, conflicting_uid, their_priority) VALUES (?, ?, ?)",
            (team_event_id, conflicting_uid, their_priority),
        )
        return cur.lastrowid


def get_conflicts(team_event_id: int) -> list[dict]:
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM team_event_conflicts WHERE team_event_id=?",
            (team_event_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def resolve_conflict(conflict_id: int, resolution: str) -> None:
    """resolution: 'accepted' | 'declined' | 'escalated'"""
    with db_conn() as conn:
        conn.execute(
            "UPDATE team_event_conflicts SET resolution=? WHERE id=?",
            (resolution, conflict_id),
        )


def get_pending_conflicts_for_user(uid: int) -> list[dict]:
    with db_conn() as conn:
        rows = conn.execute(
            """SELECT c.*, e.title, e.start_dt, e.end_dt, e.priority AS org_priority,
                      e.organizer_id
               FROM team_event_conflicts c
               JOIN team_events e ON e.id = c.team_event_id
               WHERE c.conflicting_uid=? AND c.resolution='pending'""",
            (uid,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_connected_users() -> list[dict]:
    """Google Calendar 연동된 모든 승인 사용자 반환."""
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT telegram_id, full_name, google_email FROM users "
            "WHERE status='APPROVED' AND google_token IS NOT NULL"
        ).fetchall()
        return [dict(r) for r in rows]


def get_team_events_by_range(start_dt: str, end_dt: str) -> list[dict]:
    """
    start_dt ~ end_dt 기간 내 팀 이벤트를 등록자 이름과 함께 반환.
    겹침 조건: 이벤트.start < end_dt AND 이벤트.end > start_dt
    """
    with db_conn() as conn:
        rows = conn.execute(
            """SELECT te.*, u.full_name AS organizer_name
               FROM team_events te
               LEFT JOIN users u ON u.telegram_id = te.organizer_id
               WHERE te.status = 'active'
               AND te.start_dt < ? AND te.end_dt > ?
               ORDER BY te.start_dt ASC""",
            (end_dt, start_dt),
        ).fetchall()
        return [dict(r) for r in rows]


def add_attendee(team_event_id: int, user_id: int) -> None:
    """참석 초대 추가. 이미 존재하면 무시."""
    with db_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO team_event_attendees (team_event_id, user_id) VALUES (?, ?)",
            (team_event_id, user_id),
        )


def update_attendee_status(team_event_id: int, user_id: int, status: str) -> None:
    """참석 상태 업데이트: pending / accepted / declined"""
    with db_conn() as conn:
        conn.execute(
            "UPDATE team_event_attendees SET status=?, responded_at=datetime('now') "
            "WHERE team_event_id=? AND user_id=?",
            (status, team_event_id, user_id),
        )


def get_attendees(team_event_id: int) -> list[dict]:
    """팀 이벤트 참석자 목록 (이름 포함)."""
    with db_conn() as conn:
        rows = conn.execute(
            """SELECT ta.*, u.full_name
               FROM team_event_attendees ta
               LEFT JOIN users u ON u.telegram_id = ta.user_id
               WHERE ta.team_event_id=?
               ORDER BY ta.status, u.full_name""",
            (team_event_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_pending_attendance_for_user(user_id: int) -> list[dict]:
    """사용자에게 대기 중인 참석 요청 목록."""
    with db_conn() as conn:
        rows = conn.execute(
            """SELECT ta.*, te.title, te.start_dt, te.end_dt, te.organizer_id,
                      u.full_name AS organizer_name
               FROM team_event_attendees ta
               JOIN team_events te ON te.id = ta.team_event_id
               LEFT JOIN users u ON u.telegram_id = te.organizer_id
               WHERE ta.user_id=? AND ta.status='pending'""",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_overlapping_team_events(
    start_dt: str, end_dt: str, exclude_uid: int | None = None
) -> list[dict]:
    """
    start_dt ~ end_dt 시간대와 겹치는 기존 팀 이벤트를 반환.
    exclude_uid: 본인(등록자) 일정은 제외.
    겹침 조건: 기존.start < 신규.end AND 기존.end > 신규.start
    """
    with db_conn() as conn:
        if exclude_uid is not None:
            rows = conn.execute(
                """SELECT te.*, u.full_name AS organizer_name
                   FROM team_events te
                   LEFT JOIN users u ON u.telegram_id = te.organizer_id
                   WHERE te.status = 'active'
                   AND te.start_dt < ? AND te.end_dt > ?
                   AND te.organizer_id != ?""",
                (end_dt, start_dt, exclude_uid),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT te.*, u.full_name AS organizer_name
                   FROM team_events te
                   LEFT JOIN users u ON u.telegram_id = te.organizer_id
                   WHERE te.status = 'active'
                   AND te.start_dt < ? AND te.end_dt > ?""",
                (end_dt, start_dt),
            ).fetchall()
        return [dict(r) for r in rows]
