"""
DB 연결 및 스키마 초기화
"""
import sqlite3
from config import DATABASE_PATH


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """앱 시작 시 1회 호출 — 테이블이 없으면 생성합니다."""
    conn = get_conn()
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

    conn.commit()
    conn.close()
