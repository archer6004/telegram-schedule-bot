"""
DB 자동 백업 서비스

- 매일 새벽 2시 실행
- bot.db → BACKUP_DIR/bot_YYYYMMDD.db 복사
- 7일치 보관, 초과분 자동 삭제
"""
import shutil
import logging
from datetime import datetime, timedelta
from pathlib import Path

from config import DATABASE_PATH, BACKUP_DIR, TIMEZONE
import pytz

logger = logging.getLogger(__name__)
tz = pytz.timezone(TIMEZONE)


def run_backup() -> str:
    """DB를 날짜 이름으로 백업 디렉토리에 복사합니다. 백업 파일 경로를 반환합니다."""
    src = Path(DATABASE_PATH)
    if not src.exists():
        logger.warning("backup: DB 파일을 찾을 수 없습니다 — %s", src)
        return ""

    backup_dir = Path(BACKUP_DIR)
    backup_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now(tz).strftime("%Y%m%d")
    dest = backup_dir / f"bot_{today}.db"

    shutil.copy2(src, dest)
    logger.info("backup: %s → %s (%d bytes)", src.name, dest.name, dest.stat().st_size)

    _purge_old_backups(backup_dir, keep_days=7)
    return str(dest)


def _purge_old_backups(backup_dir: Path, keep_days: int = 7) -> None:
    """keep_days일보다 오래된 백업 파일을 삭제합니다."""
    cutoff = datetime.now(tz) - timedelta(days=keep_days)
    for f in sorted(backup_dir.glob("bot_*.db")):
        # 파일명에서 날짜 추출: bot_20260326.db
        try:
            date_str = f.stem.split("_")[1]          # "20260326"
            file_date = datetime.strptime(date_str, "%Y%m%d").replace(
                tzinfo=tz
            )
            if file_date < cutoff:
                f.unlink()
                logger.info("backup: 오래된 백업 삭제 — %s", f.name)
        except (IndexError, ValueError):
            pass  # 날짜 파싱 실패 시 무시
