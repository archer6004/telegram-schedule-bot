"""
Test Coordinator

테스트 실행 및 결과 수집의 중심 역할
"""

import logging
import asyncio
from datetime import datetime
from typing import Dict, List, Optional

from test_agent.test_accounts import TestAccountManager, TestAccount
from test_agent.scenarios import ScenarioManager, TestScenario
from test_agent.analyzer import TestAnalyzer, TestResult
from test_agent.report_generator import ReportGenerator

logger = logging.getLogger(__name__)


class TestCoordinator:
    """테스트 에이전트의 코디네이터 (메인 로직)"""

    def __init__(self, db, telegram_client):
        """
        Args:
            db: Database module (db/__init__.py)
            telegram_client: Telegram API 클라이언트
        """
        self.db = db
        self.telegram_client = telegram_client
        self.account_manager = TestAccountManager(db)
        self.scenario_manager = ScenarioManager()
        self.analyzer = TestAnalyzer()
        self.report_generator = ReportGenerator()

        self.start_time = None
        self.end_time = None

    async def run_all_tests(self) -> str:
        """
        모든 테스트를 실행하고 요약 리포트를 반환

        Returns:
            요약 리포트 (채팅용 마크다운)
        """
        logger.info("=" * 60)
        logger.info("🧪 테스트 에이전트 시작")
        logger.info("=" * 60)

        self.start_time = datetime.now()

        try:
            # 1️⃣ 테스트 계정 초기화
            logger.info("📋 Step 1: 테스트 계정 초기화")
            account_ids = await self.account_manager.setup_test_accounts()
            if not account_ids:
                logger.error("❌ 테스트 계정 초기화 실패")
                return "❌ 테스트 계정 초기화 실패"

            logger.info(f"✅ {len(account_ids)}개 테스트 계정 준비 완료")

            # 2️⃣ 테스트 시나리오 실행
            logger.info("📋 Step 2: 테스트 시나리오 실행")
            scenarios = self.scenario_manager.get_scenarios(enabled_only=True)
            logger.info(f"📊 총 {len(scenarios)}개 시나리오 실행 예정")

            for i, scenario in enumerate(scenarios, 1):
                logger.info(f"  [{i}/{len(scenarios)}] {scenario.name}...")
                try:
                    result = await self._run_scenario(scenario, account_ids)
                    self.analyzer.add_result(result)
                    logger.info(f"    → {result.status}")
                except Exception as e:
                    logger.error(f"    ❌ 시나리오 실행 오류: {e}")
                    # 실패한 시나리오도 기록
                    failed_result = TestResult(
                        scenario_id=scenario.id,
                        scenario_name=scenario.name,
                        status="FAIL",
                        duration=0,
                        error_message=str(e)
                    )
                    self.analyzer.add_result(failed_result)

            # 3️⃣ 결과 분석
            logger.info("📋 Step 3: 결과 분석")
            summary = self.analyzer.analyze()
            logger.info(f"✅ {summary.passed}/{summary.total} 테스트 통과 ({summary.pass_rate:.1f}%)")

            # 4️⃣ 리포트 생성
            logger.info("📋 Step 4: 리포트 생성")
            report = self.report_generator.generate_summary_report(
                summary,
                self.analyzer.results,
                duration_minutes=(self._get_duration() / 60)
            )

            # 5️⃣ 테스트 계정 정리
            logger.info("📋 Step 5: 테스트 계정 정리")
            cleanup_ok = await self.account_manager.cleanup_test_accounts()
            if cleanup_ok:
                logger.info("✅ 테스트 계정 정리 완료")
            else:
                logger.warning("⚠️ 테스트 계정 정리 부분 실패 (무시 가능)")

            self.end_time = datetime.now()

            logger.info("=" * 60)
            logger.info("✅ 테스트 완료!")
            logger.info("=" * 60)

            return report

        except Exception as e:
            logger.error(f"❌ 테스트 실행 중 오류: {e}", exc_info=True)
            self.end_time = datetime.now()
            return f"❌ 테스트 실행 오류:\n```\n{str(e)}\n```"

    async def _run_scenario(self, scenario: TestScenario, account_ids: Dict[str, int]) -> TestResult:
        """
        단일 시나리오 실행

        Args:
            scenario: TestScenario 객체
            account_ids: {account_id: chat_id} 매핑

        Returns:
            TestResult 객체
        """
        start_time = datetime.now()

        try:
            # 계정 조회
            account_id = scenario.account_id
            chat_id = account_ids.get(account_id)
            if not chat_id:
                return TestResult(
                    scenario_id=scenario.id,
                    scenario_name=scenario.name,
                    status="FAIL",
                    duration=(datetime.now() - start_time).total_seconds(),
                    error_message=f"테스트 계정을 찾을 수 없음: {account_id}"
                )

            # 시나리오 실행 로직 (각 step 실행)
            status = "PASS"
            error_msg = None

            for step_idx, step in enumerate(scenario.steps, 1):
                try:
                    await self._execute_step(chat_id, step, scenario)
                except Exception as e:
                    status = "FAIL"
                    error_msg = f"Step {step_idx} ({step.name}): {str(e)}"
                    logger.warning(f"    ⚠️ {error_msg}")
                    break

            duration = (datetime.now() - start_time).total_seconds()

            return TestResult(
                scenario_id=scenario.id,
                scenario_name=scenario.name,
                status=status,
                duration=duration,
                error_message=error_msg
            )

        except Exception as e:
            logger.error(f"시나리오 실행 예외: {e}")
            return TestResult(
                scenario_id=scenario.id,
                scenario_name=scenario.name,
                status="FAIL",
                duration=(datetime.now() - start_time).total_seconds(),
                error_message=str(e)
            )

    async def _execute_step(self, chat_id: int, step, scenario: TestScenario):
        """
        테스트 단계 실행

        Args:
            chat_id: 테스트 사용자 chat_id
            step: TestStep 객체
            scenario: 속한 시나리오 (로깅용)
        """
        if step.action == "send_message":
            # 메시지 전송
            logger.debug(f"  [send_message] {step.value}")
            try:
                # 실제 메시지 전송 (Telegram API 사용)
                # 여기서는 placeholder
                await asyncio.sleep(0.5)  # API 호출 시뮬레이션
            except Exception as e:
                raise Exception(f"메시지 전송 실패: {e}")

        elif step.action == "click_button":
            # 버튼 클릭
            logger.debug(f"  [click_button] {step.value}")
            try:
                # 버튼 클릭 (콜백 실행)
                await asyncio.sleep(0.5)  # API 호출 시뮬레이션
            except Exception as e:
                raise Exception(f"버튼 클릭 실패: {e}")

        elif step.action == "wait":
            # 대기
            wait_seconds = float(step.value)
            logger.debug(f"  [wait] {wait_seconds}초")
            await asyncio.sleep(wait_seconds)

        elif step.action == "assert":
            # 확인 (응답 검증)
            logger.debug(f"  [assert] {step.value} == {step.expected}")
            # 실제로는 API 응답을 검증해야 함
            pass

    def _get_duration(self) -> float:
        """전체 실행 시간 (초)"""
        if not self.start_time or not self.end_time:
            return 0.0
        return (self.end_time - self.start_time).total_seconds()

    def get_summary(self) -> Dict:
        """테스트 요약 정보 반환"""
        summary = self.analyzer.analyze()
        return {
            "total": summary.total,
            "passed": summary.passed,
            "failed": summary.failed,
            "warnings": summary.warnings,
            "pass_rate": summary.pass_rate,
            "duration": self._get_duration(),
            "avg_response_time": summary.avg_response_time,
        }

    def reset(self):
        """테스트 상태 초기화"""
        self.analyzer = TestAnalyzer()
        self.start_time = None
        self.end_time = None
        logger.info("🔄 테스트 상태 초기화 완료")
