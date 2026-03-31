"""
Test Handler

테스트 에이전트 실행 핸들러 (동콕 버튼)
"""

import logging
import asyncio
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler

from test_agent.coordinator import TestCoordinator

logger = logging.getLogger(__name__)

# 전역 coordinator 인스턴스
_coordinator: TestCoordinator = None


def set_coordinator(coordinator: TestCoordinator):
    """Coordinator 인스턴스 설정 (main.py에서 호출)"""
    global _coordinator
    _coordinator = coordinator
    logger.info("✅ Test Coordinator 설정 완료")


async def cmd_test(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /test_agent 명령어 처리

    사용자가 명령어로 테스트를 수동 실행할 때
    """
    if not _coordinator:
        await update.message.reply_text(
            "❌ 테스트 에이전트가 초기화되지 않았습니다."
        )
        return

    user_id = update.message.from_user.id
    logger.info(f"🧪 테스트 실행 요청: user_id={user_id}")

    # 진행 중 메시지
    progress_msg = await update.message.reply_text(
        "🧪 *테스트 실행 중...*\n\n"
        "• 테스트 계정 초기화 중\n"
        "• 시나리오 실행 중\n"
        "• 결과 분석 중\n\n"
        "잠시만 기다려주세요 ⏳",
        parse_mode="Markdown"
    )

    try:
        # 테스트 상태 초기화
        _coordinator.reset()

        # 테스트 실행 (비동기)
        report = await _coordinator.run_all_tests()

        # 결과 업데이트
        await progress_msg.edit_text(report, parse_mode="Markdown")

        # 요약 정보
        summary = _coordinator.get_summary()
        await update.message.reply_text(
            f"📊 *테스트 완료!*\n\n"
            f"✅ 통과: {summary['passed']}/{summary['total']} ({summary['pass_rate']:.1f}%)\n"
            f"⏱️ 소요시간: {summary['duration']:.1f}초\n"
            f"📈 평균 응답: {summary['avg_response_time']*1000:.0f}ms",
            parse_mode="Markdown"
        )

    except Exception as e:
        logger.error(f"❌ 테스트 실행 오류: {e}", exc_info=True)
        await progress_msg.edit_text(
            f"❌ *테스트 실행 오류*\n\n```\n{str(e)[:200]}\n```",
            parse_mode="Markdown"
        )


async def test_button_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    '🧪 테스트 실행' 버튼 콜백 (메인 메뉴에서 호출)
    """
    query = update.callback_query
    await query.answer()

    if not _coordinator:
        await query.edit_message_text(
            "❌ 테스트 에이전트가 초기화되지 않았습니다."
        )
        return

    user_id = query.from_user.id
    logger.info(f"🧪 테스트 버튼 클릭: user_id={user_id}")

    # 진행 중 메시지
    await query.edit_message_text(
        "🧪 *테스트 실행 중...*\n\n"
        "• 테스트 계정 초기화\n"
        "• 시나리오 실행\n"
        "• 결과 분석\n\n"
        "잠시만 기다려주세요 ⏳",
        parse_mode="Markdown"
    )

    try:
        # 테스트 상태 초기화
        _coordinator.reset()

        # 테스트 실행
        report = await _coordinator.run_all_tests()

        # 결과 전송
        await ctx.bot.send_message(
            chat_id=user_id,
            text=report,
            parse_mode="Markdown"
        )

        # 요약 정보
        summary = _coordinator.get_summary()
        summary_text = (
            f"📊 *테스트 완료!*\n\n"
            f"✅ 통과: {summary['passed']}/{summary['total']} ({summary['pass_rate']:.1f}%)\n"
            f"⏱️ 소요시간: {summary['duration']:.1f}초\n"
            f"📈 평균 응답: {summary['avg_response_time']*1000:.0f}ms"
        )
        await ctx.bot.send_message(
            chat_id=user_id,
            text=summary_text,
            parse_mode="Markdown"
        )

        # 원본 메시지 업데이트
        await query.edit_message_text("✅ 테스트가 시작되었습니다.")

    except Exception as e:
        logger.error(f"❌ 테스트 버튼 처리 오류: {e}", exc_info=True)
        error_msg = (
            f"❌ *테스트 실행 오류*\n\n"
            f"```\n{str(e)[:200]}\n```"
        )
        await ctx.bot.send_message(
            chat_id=user_id,
            text=error_msg,
            parse_mode="Markdown"
        )


def test_handlers():
    """테스트 핸들러 등록"""
    return [
        CommandHandler("test_agent", cmd_test),
        CallbackQueryHandler(test_button_callback, pattern=r"^test_run$"),
    ]
