"""
Test Accounts Management

테스트용 사용자 계정 관리
"""

import logging
from dataclasses import dataclass
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class TestAccount:
    """테스트 계정 정보"""
    account_id: str
    chat_id: Optional[int] = None
    role: str = "MEMBER"  # OWNER, ADMIN, MEMBER
    google_connected: bool = False
    purpose: str = ""


class TestAccountManager:
    """테스트 계정 관리자"""

    # 테스트 계정 정의
    TEST_ACCOUNTS: Dict[str, TestAccount] = {
        "test_user_001": TestAccount(
            account_id="test_user_001",
            role="MEMBER",
            google_connected=False,
            purpose="신규 사용자 가입 흐름"
        ),
        "test_user_002": TestAccount(
            account_id="test_user_002",
            role="MEMBER",
            google_connected=True,
            purpose="Google 연동된 사용자"
        ),
        "test_user_003": TestAccount(
            account_id="test_user_003",
            role="OWNER",
            google_connected=True,
            purpose="팀장 권한 테스트"
        ),
        "test_user_004": TestAccount(
            account_id="test_user_004",
            role="ADMIN",
            google_connected=True,
            purpose="관리자 권한 테스트"
        ),
        "test_user_005": TestAccount(
            account_id="test_user_005",
            role="MEMBER",
            google_connected=True,
            purpose="일반 팀원 테스트"
        ),
    }

    def __init__(self, db):
        """
        Args:
            db: Database module (db/__init__.py)
        """
        self.db = db
        self.accounts = self.TEST_ACCOUNTS.copy()

    async def setup_test_accounts(self) -> Dict[str, int]:
        """
        테스트 계정 초기화 및 생성

        Returns:
            {account_id: chat_id} 매핑
        """
        result = {}

        for account_id, account_info in self.accounts.items():
            try:
                # DB에서 계정 찾기 또는 생성
                existing = self.db.get_user_by_nickname(account_id)

                if existing:
                    account_info.chat_id = existing['user_id']
                    logger.info(f"✅ 기존 테스트 계정 사용: {account_id} (chat_id={existing['user_id']})")
                else:
                    # 새로운 테스트 계정 생성
                    chat_id = int(account_id.split("_")[-1]) + 999000000  # 고유 ID 생성

                    self.db.add_user(
                        user_id=chat_id,
                        first_name=account_id,
                        last_name="TEST",
                        is_approved=True,
                        role=account_info.role
                    )

                    account_info.chat_id = chat_id
                    logger.info(f"✅ 새로운 테스트 계정 생성: {account_id} (chat_id={chat_id})")

                result[account_id] = account_info.chat_id

            except Exception as e:
                logger.error(f"❌ 테스트 계정 설정 실패 {account_id}: {e}")

        return result

    async def cleanup_test_accounts(self) -> bool:
        """
        테스트 계정 정리 (모든 데이터 삭제)

        Returns:
            성공 여부
        """
        try:
            for account_id in self.accounts.keys():
                chat_id = self.accounts[account_id].chat_id
                if chat_id:
                    # 테스트 계정 관련 모든 데이터 삭제
                    self.db.delete_user(chat_id)
                    logger.info(f"✅ 테스트 계정 정리: {account_id}")

            return True
        except Exception as e:
            logger.error(f"❌ 테스트 계정 정리 실패: {e}")
            return False

    def get_account(self, account_id: str) -> Optional[TestAccount]:
        """테스트 계정 조회"""
        return self.accounts.get(account_id)

    def get_account_by_role(self, role: str) -> Optional[TestAccount]:
        """역할별 테스트 계정 조회"""
        for account in self.accounts.values():
            if account.role == role:
                return account
        return None

    def list_accounts(self) -> Dict[str, TestAccount]:
        """모든 테스트 계정 조회"""
        return self.accounts.copy()
