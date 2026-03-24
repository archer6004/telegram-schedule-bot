import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_TELEGRAM_IDS = [
    int(i.strip()) for i in os.getenv("ADMIN_TELEGRAM_IDS", "").split(",") if i.strip()
]
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
DATABASE_PATH = os.getenv("DATABASE_PATH", "bot.db")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Seoul")

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]

# models.user 에서 정의 — 하위 호환을 위해 re-export
from models.user import UserStatus  # noqa: E402

# 리마인더 기본 설정 (분 단위)
DEFAULT_REMINDER_MINUTES = [60, 10]  # 1시간 전, 10분 전
