"""
Telegram 스케줄 챗봇 — 메인 진입점
실행: python main.py
"""
import logging
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters,
)

from config import TELEGRAM_BOT_TOKEN
from db.connection import init_db

from handlers.auth_handler import (
    cmd_start, cmd_status,
    registration_conv, connect_conv, reconnect_callback,
)
from handlers.admin_handler import cmd_admin, admin_callback, cmd_setup_team
from handlers.calendar_handler import (
    cmd_help, cmd_today, cmd_week, cmd_free, handle_message,
    help_callback, schedule_view_callback,
)
from handlers.wizard_handler import wizard_callback
from handlers.team_handler import team_callbacks
from handlers.error_handler import handle_error
from services.scheduler_service import init_scheduler

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main():
    # DB 초기화
    init_db()
    logger.info("DB initialized")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # ── ConversationHandlers (우선순위 높음) ───────────────
    app.add_handler(registration_conv())
    app.add_handler(connect_conv())

    # ── 일반 커맨드 ────────────────────────────────────────
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CommandHandler("today",  cmd_today))
    app.add_handler(CommandHandler("week",   cmd_week))
    app.add_handler(CommandHandler("free",   cmd_free))
    app.add_handler(CommandHandler("admin",      cmd_admin))
    app.add_handler(CommandHandler("setup_team", cmd_setup_team))

    # ── 인라인 버튼 콜백 ───────────────────────────────────
    # 위저드 콜백을 먼저 등록 (pattern 필터로 wiz_* 만 처리)
    app.add_handler(CallbackQueryHandler(wizard_callback,         pattern="^wiz_"))
    app.add_handler(CallbackQueryHandler(reconnect_callback,      pattern="^reconnect_"))
    app.add_handler(CallbackQueryHandler(help_callback,           pattern="^help:"))
    app.add_handler(CallbackQueryHandler(schedule_view_callback,  pattern="^view:"))
    for handler in team_callbacks():
        app.add_handler(handler)
    app.add_handler(CallbackQueryHandler(admin_callback))

    # ── 자연어 메시지 (가장 마지막) ───────────────────────
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # ── 중앙 에러 핸들러 ───────────────────────────────────
    app.add_error_handler(handle_error)

    # ── 스케줄러 시작 (리마인더 + 아침 브리핑) ─────────────
    init_scheduler(app.bot)

    logger.info("Bot started — polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
