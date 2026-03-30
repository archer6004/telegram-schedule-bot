"""
DB 연결 및 스키마 초기화

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[PROTECTED MODULE] — 수정 전 반드시 사용자 승인 필요
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
이 파일은 모든 DB 작업의 기반입니다.

  db_conn()   → 모든 _repo.py 파일이 사용하는 트랜잭션 매니저
                규칙: commit/rollback/close 순서 변경 금지.
                      변경 시 모든 DB 저장 작업에 영향.

  get_conn()  → WAL 모드, foreign_keys, timeout 설정
                규칙: PRAGMA 설정 변경은 DB 동작 방식 전체에 영향.
                      check_same_thread=False 제거 시 비동기 환경 크래시.

  init_db()   → 테이블 스키마 정의
                규칙: 컬럼 추가는 마이그레이션 블록(ALTER TABLE)에 추가할 것.
                      기존 컬럼 타입·이름 변경 금지 (데이터 손실 위험).

의존 파일: db/user_repo.py, db/team_repo.py, db/reminder_repo.py,
           db/settings_repo.py (모두 with db_conn() 패턴 사용)

수정이 필요할 경우: 변경 내용과 영향 범위를 사용자에게 상세히
설명하고 승인을 받은 후 관련 파일을 모두 함께 수정할 것.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import sqlite3
import logging
from contextlib import contextmanager
from config import DATABASE_PATH

logger = logging.getLogger(__name__)


def get_conn() -> sqlite3.Connection:
    """연결 반환. 반드시 호출자가 close() 해야 합니다. db_conn() 사용을 권장합니다."""
    conn = sqlite3.connect(
        DATABASE_PATH,
        check_same_thread=False,  # 멀티스레드/비동기 환경 허용
        timeout=10,               # 10초 내 lock 해제 안되면 OperationalError
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db_conn():
    """
    안전한 DB 연결 컨텍스트 매니저.
    - 정상 종료: commit 후 close
    - 예외 발생: rollback 후 close (연결 누수 없음)

    사용법:
        with db_conn() as conn:
            conn.execute(...)
    """
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """앱 시작 시 1회 호출 — 테이블이 없으면 생성합니다."""
    conn = get_conn()  # init_db는 직접 관리 (with db_conn()은 순환참조 방지)
    c = conn.cursor()

    # 사용자 테이블
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id     INTEGER PRIMARY KEY,
            username        TEXT,
            full_name       TEXT,
            department      TEXT,
            purpose         TEXT,
            status          TEXT DEFAULT 'PENDING',
            google_token    TEXT,
            created_at      TEXT DEFAULT (datetime('now')),
            approved_at     TEXT,
            expires_at      TEXT,
            rejected_reason TEXT
        )
    """)

    # 리마인더 테이블
    # ON DELETE CASCADE: users 행 삭제 시 해당 리마인더도 자동 삭제
    # Idea from workspace/telegram-chatbot ON DELETE CASCADE pattern
    c.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id     INTEGER NOT NULL,
            event_id        TEXT NOT NULL,
            event_title     TEXT NOT NULL,
            event_datetime  TEXT NOT NULL,
            remind_at       TEXT NOT NULL,
            sent            INTEGER DEFAULT 0,
            created_at      TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (telegram_id) REFERENCES users(telegram_id) ON DELETE CASCADE
        )
    """)

    # 감사 로그 테이블
    c.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            action      TEXT NOT NULL,
            detail      TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        )
    """)

    # 팀 이벤트 테이블
    c.execute("""
        CREATE TABLE IF NOT EXISTS team_events (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            title        TEXT NOT NULL,
            start_dt     TEXT NOT NULL,
            end_dt       TEXT NOT NULL,
            organizer_id INTEGER NOT NULL,
            priority     TEXT DEFAULT 'yellow',
            google_event_id TEXT,
            status       TEXT DEFAULT 'active',
            created_at   TEXT DEFAULT (datetime('now'))
        )
    """)

    # 팀 이벤트 충돌 테이블
    c.execute("""
        CREATE TABLE IF NOT EXISTS team_event_conflicts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            team_event_id   INTEGER NOT NULL,
            conflicting_uid INTEGER NOT NULL,
            their_priority  TEXT DEFAULT 'yellow',
            resolution      TEXT DEFAULT 'pending',
            created_at      TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (team_event_id) REFERENCES team_events(id)
        )
    """)

    # 앱 설정 키-값 테이블
    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # 팀 이벤트 참석자 테이블 (참석 초대 + 응답 추적)
    c.execute("""
        CREATE TABLE IF NOT EXISTS team_event_attendees (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            team_event_id   INTEGER NOT NULL,
            user_id         INTEGER NOT NULL,
            status          TEXT DEFAULT 'pending',
            responded_at    TEXT,
            UNIQUE(team_event_id, user_id),
            FOREIGN KEY (team_event_id) REFERENCES team_events(id)
        )
    """)

    # 기존 DB 마이그레이션
    for col, definition in [
        ("google_email", "TEXT"),
        ("role",         "TEXT DEFAULT 'MEMBER'"),
    ]:
        try:
            c.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
            logger.info("마이그레이션: users.%s 컬럼 추가됨", col)
        except sqlite3.OperationalError:
            pass  # 이미 존재하는 컬럼 — 정상

    # 인덱스 (없으면 생성, 있으면 무시)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_reminders_sent_remind_at
        ON reminders (sent, remind_at)
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_users_status
        ON users (status)
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_team_events_dt
        ON team_events (start_dt, end_dt)
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_audit_log_created_at
        ON audit_log (created_at)
    """)

    conn.commit()
    conn.close()
