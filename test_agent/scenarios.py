"""
Test Scenarios

기본 테스트 시나리오 정의 (기본만)
"""

import logging
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class TestStep:
    """테스트 단계"""
    name: str
    action: str  # "send_message", "click_button", "wait", "assert"
    value: str
    expected: Optional[str] = None
    timeout: int = 10  # 초


@dataclass
class TestScenario:
    """테스트 시나리오"""
    id: str
    name: str
    description: str
    account_id: str
    steps: List[TestStep]
    priority: int = 1  # 1=높음, 2=중간, 3=낮음
    enabled: bool = True


class ScenarioManager:
    """테스트 시나리오 관리자"""

    SCENARIOS: List[TestScenario] = [
        # 1. 기본 메뉴 확인
        TestScenario(
            id="basic_menu",
            name="기본 메뉴 확인",
            description="메인 메뉴의 모든 버튼이 정상 표시되는지 확인",
            account_id="test_user_001",
            steps=[
                TestStep(
                    name="메뉴 표시",
                    action="send_message",
                    value="/start",
                    expected="📅 일정 등록"
                ),
                TestStep(
                    name="메뉴 버튼 확인",
                    action="assert",
                    value="menu_buttons",
                    expected="['📅 일정 등록', '👥 팀 일정 등록', '📋 오늘 일정', '📋 이번 주 일정', '⏱ 빈 시간 찾기', '🌤 오늘 날씨', '🗑 일정 취소', '❓ 도움말']"
                ),
            ],
            priority=1
        ),

        # 2. 도움말 메뉴 확인
        TestScenario(
            id="help_menu",
            name="도움말 메뉴",
            description="도움말 버튼 클릭 시 모든 헬프 버튼 정상 작동",
            account_id="test_user_002",
            steps=[
                TestStep(
                    name="도움말 버튼 클릭",
                    action="click_button",
                    value="❓ 도움말",
                    expected="📖 시작 가이드"
                ),
                TestStep(
                    name="가이드 버튼 확인",
                    action="assert",
                    value="help_buttons",
                    expected="['📖 시작 가이드', '📅 개인 일정 설명', '👥 팀 일정 설명', '🔔 리마인더 설정', '🌤 오늘 날씨']"
                ),
            ],
            priority=1
        ),

        # 3. 일정 등록 (개인)
        TestScenario(
            id="personal_event_create",
            name="개인 일정 등록",
            description="개인 일정 등록 기능 테스트",
            account_id="test_user_003",
            steps=[
                TestStep(
                    name="일정 등록 버튼 클릭",
                    action="click_button",
                    value="📅 일정 등록",
                    expected="일정 제목"
                ),
                TestStep(
                    name="일정 제목 입력",
                    action="send_message",
                    value="테스트 회의",
                    expected="일정 시간"
                ),
                TestStep(
                    name="일정 시간 입력",
                    action="send_message",
                    value="오후 3시",
                    expected="저장 완료"
                ),
            ],
            priority=1
        ),

        # 4. 일정 조회 (오늘)
        TestScenario(
            id="view_today_events",
            name="오늘 일정 조회",
            description="'📋 오늘 일정' 버튼 작동 확인",
            account_id="test_user_004",
            steps=[
                TestStep(
                    name="오늘 일정 버튼 클릭",
                    action="click_button",
                    value="📋 오늘 일정",
                    expected="일정 목록 또는 '없습니다'"
                ),
            ],
            priority=1
        ),

        # 5. 일정 조회 (이번 주)
        TestScenario(
            id="view_week_events",
            name="이번 주 일정 조회",
            description="'📋 이번 주 일정' 버튼 작동 확인",
            account_id="test_user_005",
            steps=[
                TestStep(
                    name="이번 주 일정 버튼 클릭",
                    action="click_button",
                    value="📋 이번 주 일정",
                    expected="주간 일정 목록 또는 '없습니다'"
                ),
            ],
            priority=1
        ),

        # 6. 날씨 조회
        TestScenario(
            id="check_weather",
            name="날씨 확인",
            description="'🌤 오늘 날씨' 버튼 작동 확인",
            account_id="test_user_001",
            steps=[
                TestStep(
                    name="날씨 버튼 클릭",
                    action="click_button",
                    value="🌤 오늘 날씨",
                    expected="기온|습도|강수확률"
                ),
            ],
            priority=2
        ),

        # 7. Google 연동 버튼 (미연동 사용자)
        TestScenario(
            id="google_connect_button",
            name="Google 연동 버튼",
            description="미연동 사용자가 Google 연동 버튼을 보는지 확인",
            account_id="test_user_001",
            steps=[
                TestStep(
                    name="메뉴 표시",
                    action="send_message",
                    value="/start",
                    expected="Google Calendar"
                ),
            ],
            priority=2
        ),

        # 8. 권한별 메뉴 (OWNER vs MEMBER)
        TestScenario(
            id="role_based_menu",
            name="권한별 메뉴 차이",
            description="OWNER와 MEMBER의 메뉴 차이 확인",
            account_id="test_user_003",  # OWNER
            steps=[
                TestStep(
                    name="메뉴 표시 (OWNER)",
                    action="send_message",
                    value="/start",
                    expected="관리자"  # OWNER 메뉴에만 있음
                ),
            ],
            priority=2
        ),
    ]

    def __init__(self):
        self.scenarios = self.SCENARIOS.copy()

    def get_scenarios(self, enabled_only: bool = True) -> List[TestScenario]:
        """시나리오 조회"""
        if enabled_only:
            return [s for s in self.scenarios if s.enabled]
        return self.scenarios

    def get_scenario(self, scenario_id: str) -> Optional[TestScenario]:
        """특정 시나리오 조회"""
        for scenario in self.scenarios:
            if scenario.id == scenario_id:
                return scenario
        return None

    def get_scenarios_by_priority(self, priority: int) -> List[TestScenario]:
        """우선순위별 시나리오 조회"""
        return [s for s in self.scenarios if s.priority == priority and s.enabled]

    def count_scenarios(self, enabled_only: bool = True) -> int:
        """시나리오 개수"""
        if enabled_only:
            return len([s for s in self.scenarios if s.enabled])
        return len(self.scenarios)

    def list_scenario_names(self) -> List[str]:
        """시나리오 이름 목록"""
        return [f"[{s.priority}] {s.name}" for s in self.scenarios if s.enabled]
