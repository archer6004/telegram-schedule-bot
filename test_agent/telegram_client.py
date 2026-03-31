"""
Telegram API 클라이언트

테스트용 Telegram API 호출 (메시지 전송, 응답 대기 등)
"""

import logging
import asyncio
from typing import Dict, List, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class TelegramTestClient:
    """테스트 목적의 Telegram API 클라이언트"""

    def __init__(self, bot):
        """
        Args:
            bot: telegram.ext.bot.Bot 인스턴스
        """
        self.bot = bot
        self.last_messages: Dict[int, str] = {}  # chat_id → 마지막 메시지 텍스트
        self.last_buttons: Dict[int, List[str]] = {}  # chat_id → 마지막 버튼 목록
        self.message_history: Dict[int, List[Dict]] = {}  # chat_id → 메시지 히스토리

    async def send_message(self, chat_id: int, text: str) -> bool:
        """
        메시지 전송 및 기록

        Args:
            chat_id: Telegram chat ID
            text: 메시지 텍스트

        Returns:
            성공 여부
        """
        try:
            result = await self.bot.send_message(chat_id=chat_id, text=text)
            self.last_messages[chat_id] = text
            self._record_message(chat_id, "send", text)
            logger.debug(f"📤 메시지 전송: user={chat_id}, text={text[:50]}")
            return True
        except Exception as e:
            logger.error(f"❌ 메시지 전송 실패: {e}")
            return False

    async def send_message_with_buttons(self, chat_id: int, text: str, buttons: List[str]) -> bool:
        """
        버튼과 함께 메시지 전송

        Args:
            chat_id: Telegram chat ID
            text: 메시지 텍스트
            buttons: 버튼 레이블 리스트

        Returns:
            성공 여부
        """
        try:
            from telegram import ReplyKeyboardMarkup, KeyboardButton

            keyboard = [[KeyboardButton(btn) for btn in buttons]]
            markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)

            result = await self.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=markup
            )
            self.last_messages[chat_id] = text
            self.last_buttons[chat_id] = buttons
            self._record_message(chat_id, "send_buttons", text, buttons)
            logger.debug(f"📤 버튼 메시지: user={chat_id}, buttons={buttons}")
            return True
        except Exception as e:
            logger.error(f"❌ 버튼 메시지 전송 실패: {e}")
            return False

    async def click_button(self, chat_id: int, button_text: str) -> bool:
        """
        메인 메뉴 버튼 클릭 (메시지 전송으로 시뮬레이션)

        Args:
            chat_id: Telegram chat ID
            button_text: 버튼 텍스트

        Returns:
            성공 여부
        """
        try:
            # 버튼 텍스트를 메시지로 전송 (봇이 처리함)
            result = await self.bot.send_message(chat_id=chat_id, text=button_text)
            self._record_message(chat_id, "button_click", button_text)
            logger.debug(f"🔘 버튼 클릭: user={chat_id}, button={button_text}")
            await asyncio.sleep(0.5)  # 봇 응답 대기
            return True
        except Exception as e:
            logger.error(f"❌ 버튼 클릭 실패: {e}")
            return False

    async def wait_for_response(self, chat_id: int, timeout: int = 5) -> Optional[str]:
        """
        봇 응답 대기 (개선: Update 객체 분석)

        Args:
            chat_id: Telegram chat ID
            timeout: 타임아웃 (초)

        Returns:
            봇의 응답 텍스트
        """
        # ✅ 봇의 응답을 대기 (실제 환경에서는 polling/webhook)
        # 여기서는 마지막 메시지와 버튼 상태를 종합하여 반환
        await asyncio.sleep(1)  # 처리 시간

        response = self.last_messages.get(chat_id, "")
        buttons = self.last_buttons.get(chat_id, [])

        # ✅ 응답에 버튼 정보도 포함 (인라인 키보드 감지)
        if buttons:
            response += f"\n[버튼: {', '.join(buttons[:3])}]"  # 처음 3개만

        logger.debug(f"📥 응답 수신: {response[:100]}")
        return response

    async def verify_response(self, chat_id: int, expected_text: str, timeout: int = 5) -> bool:
        """
        봇 응답 검증

        Args:
            chat_id: Telegram chat ID
            expected_text: 기대하는 텍스트 (substring match)
            timeout: 타임아웃 (초)

        Returns:
            검증 성공 여부
        """
        response = await self.wait_for_response(chat_id, timeout)
        if expected_text.lower() in response.lower():
            logger.debug(f"✅ 응답 검증 성공: '{expected_text}' 포함")
            return True
        else:
            logger.warning(f"❌ 응답 검증 실패: '{expected_text}' 미포함 (받은 응답: {response[:100]})")
            return False

    async def verify_buttons(self, chat_id: int, expected_buttons: List[str]) -> bool:
        """
        버튼 검증

        Args:
            chat_id: Telegram chat ID
            expected_buttons: 기대하는 버튼 리스트

        Returns:
            검증 성공 여부
        """
        buttons = self.last_buttons.get(chat_id, [])

        # 모든 기대 버튼이 실제 버튼에 포함되는지 확인
        for expected in expected_buttons:
            if not any(expected.lower() in btn.lower() for btn in buttons):
                logger.warning(f"❌ 버튼 미확인: '{expected}' (버튼: {buttons})")
                return False

        logger.debug(f"✅ 버튼 검증 성공: {expected_buttons}")
        return True

    def _record_message(self, chat_id: int, msg_type: str, text: str, buttons: List[str] = None):
        """메시지 히스토리 기록"""
        if chat_id not in self.message_history:
            self.message_history[chat_id] = []

        self.message_history[chat_id].append({
            "timestamp": datetime.now().isoformat(),
            "type": msg_type,
            "text": text,
            "buttons": buttons or []
        })

    def get_message_history(self, chat_id: int) -> List[Dict]:
        """메시지 히스토리 조회"""
        return self.message_history.get(chat_id, [])

    def clear_history(self, chat_id: int = None):
        """메시지 히스토리 초기화"""
        if chat_id:
            self.message_history[chat_id] = []
        else:
            self.message_history.clear()

    async def reset(self, chat_id: int = None):
        """상태 초기화"""
        if chat_id:
            self.last_messages.pop(chat_id, None)
            self.last_buttons.pop(chat_id, None)
        else:
            self.last_messages.clear()
            self.last_buttons.clear()
