"""
중앙 집중식 에러 핸들러
- Telegram의 Application.add_error_handler()에 등록
- 개별 핸들러의 반복적인 try/except 대신 이 파일에서 일관되게 처리
"""
import logging
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# 사용자에게 보여줄 에러 메시지 매핑
_ERROR_MESSAGES: dict[type, str] = {
    PermissionError: "⚠️ Google Calendar가 연동되지 않았습니다. /connect 를 입력해 주세요.",
}

_DEFAULT_MESSAGE = "⚠️ 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."


async def handle_error(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Application 레벨 에러 핸들러 — main.py에서 등록합니다."""
    err = ctx.error
    logger.error("Unhandled exception", exc_info=err)

    message = _ERROR_MESSAGES.get(type(err), _DEFAULT_MESSAGE)

    if update and update.effective_message:
        try:
            await update.effective_message.reply_text(message)
        except Exception:
            pass


def user_error_reply(exc: Exception) -> str:
    """
    핸들러 내 인라인 try/except에서 사용자 메시지를 만들 때 사용합니다.

    사용 예:
        except Exception as e:
            reply = user_error_reply(e)
    """
    return _ERROR_MESSAGES.get(type(exc), f"{_DEFAULT_MESSAGE}\n`{exc}`")
