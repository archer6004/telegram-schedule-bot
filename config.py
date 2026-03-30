import os
from pathlib import Path
from dotenv import load_dotenv

# .env는 항상 이 파일(config.py)과 같은 디렉토리에 있음
load_dotenv(Path(__file__).parent / ".env", override=True)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_TELEGRAM_IDS = [
    int(i.strip()) for i in os.getenv("ADMIN_TELEGRAM_IDS", "").split(",") if i.strip()
]
# OWNER: 최상위 권한자. 미설정 시 ADMIN_TELEGRAM_IDS와 동일.
# 역할: 사용자 역할 관리(ADMIN 임명/해제) + 팀 캘린더 설정
OWNER_TELEGRAM_IDS = [
    int(i.strip()) for i in os.getenv(
        "OWNER_TELEGRAM_IDS", os.getenv("ADMIN_TELEGRAM_IDS", "")
    ).split(",") if i.strip()
]
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
DATABASE_PATH = os.getenv(
    "DATABASE_PATH",
    str(Path.home() / ".telegram-schedule-bot" / "bot.db"),
)
BACKUP_DIR = os.getenv(
    "BACKUP_DIR",
    str(Path("/Users/josh/Library/CloudStorage/GoogleDrive-amorgan6004@gmail.com/내 드라이브/[chatbot] basic/backups")),
)
TIMEZONE = os.getenv("TIMEZONE", "Asia/Seoul")

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]

# models.user 에서 정의 — 하위 호환을 위해 re-export
from models.user import UserStatus  # noqa: E402

# 리마인더 기본 설정 (분 단위)
DEFAULT_REMINDER_MINUTES = [60, 10]  # 1시간 전, 10분 전

# Rate limiting
RATE_LIMIT_CALLS    = int(os.getenv("RATE_LIMIT_CALLS", "10"))   # 허용 횟수
RATE_LIMIT_PERIOD   = int(os.getenv("RATE_LIMIT_PERIOD", "60"))  # 초 단위 윈도우

# 입력 제한
MAX_MESSAGE_LENGTH  = int(os.getenv("MAX_MESSAGE_LENGTH", "500"))

# Claude API 타임아웃
CLAUDE_TIMEOUT_SEC  = int(os.getenv("CLAUDE_TIMEOUT_SEC", "30"))

# 날씨 서비스 위치 (기본: 서울시청)
# .env 에서 USER_LATITUDE / USER_LONGITUDE 로 재정의 가능
USER_LATITUDE  = float(os.getenv("USER_LATITUDE",  "37.5665"))
USER_LONGITUDE = float(os.getenv("USER_LONGITUDE", "126.9780"))
