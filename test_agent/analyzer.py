"""
Test Result Analyzer

테스트 결과 분석
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
import re

logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    """테스트 결과"""
    scenario_id: str
    scenario_name: str
    status: str  # "PASS", "FAIL", "WARNING"
    duration: float  # 초
    error_message: Optional[str] = None
    log_excerpt: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class TestSummary:
    """테스트 요약"""
    total: int
    passed: int
    failed: int
    warnings: int
    total_duration: float
    avg_response_time: float
    errors: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        """통과율"""
        if self.total == 0:
            return 0.0
        return (self.passed / self.total) * 100


class TestAnalyzer:
    """테스트 결과 분석기"""

    def __init__(self):
        self.results: List[TestResult] = []
        self.bot_logs: List[str] = []

    def add_result(self, result: TestResult):
        """테스트 결과 추가"""
        self.results.append(result)
        logger.info(f"📊 테스트 결과 기록: {result.scenario_name} → {result.status}")

    def add_log_excerpt(self, scenario_id: str, log_text: str):
        """로그 추가"""
        for result in self.results:
            if result.scenario_id == scenario_id:
                result.log_excerpt = log_text
                break

    def analyze(self) -> TestSummary:
        """
        테스트 결과 분석

        Returns:
            TestSummary 객체
        """
        if not self.results:
            return TestSummary(total=0, passed=0, failed=0, warnings=0, total_duration=0, avg_response_time=0)

        passed = len([r for r in self.results if r.status == "PASS"])
        failed = len([r for r in self.results if r.status == "FAIL"])
        warnings = len([r for r in self.results if r.status == "WARNING"])
        total = len(self.results)

        total_duration = sum(r.duration for r in self.results)
        avg_response_time = total_duration / total if total > 0 else 0

        errors = [r.error_message for r in self.results if r.error_message and r.status == "FAIL"]
        suggestions = self._generate_suggestions()

        summary = TestSummary(
            total=total,
            passed=passed,
            failed=failed,
            warnings=warnings,
            total_duration=total_duration,
            avg_response_time=avg_response_time,
            errors=errors,
            suggestions=suggestions
        )

        return summary

    def _generate_suggestions(self) -> List[str]:
        """개선 제안 생성"""
        suggestions = []

        # 응답 시간 분석
        slow_results = [r for r in self.results if r.duration > 2.0]
        if slow_results:
            slow_names = ", ".join([r.scenario_name for r in slow_results])
            suggestions.append(f"⚠️ 느린 응답: {slow_names} ({sum(r.duration for r in slow_results):.1f}초)")

        # 실패 분석
        failed = [r for r in self.results if r.status == "FAIL"]
        if failed:
            suggestions.append(f"❌ 실패한 테스트: {len(failed)}개 확인 필요")

        # Google 연동 관련
        google_results = [r for r in self.results if "google" in r.scenario_id.lower()]
        if google_results and any(r.status == "FAIL" for r in google_results):
            suggestions.append("🔗 Google 연동 관련 문제 - API 상태 확인 필요")

        # 권한 관련
        role_results = [r for r in self.results if "role" in r.scenario_id.lower()]
        if role_results and any(r.status == "FAIL" for r in role_results):
            suggestions.append("🔐 권한별 메뉴 차이 확인 - DB 역할 설정 검토")

        return suggestions

    def extract_bot_errors(self, log_content: str) -> List[str]:
        """
        bot.log에서 에러 추출

        Args:
            log_content: bot.log 파일 내용

        Returns:
            에러 메시지 리스트
        """
        errors = []
        lines = log_content.split('\n')

        for line in lines:
            if 'ERROR' in line or 'Exception' in line or 'Traceback' in line:
                errors.append(line.strip())

        return errors[-10:] if len(errors) > 10 else errors  # 최근 10개만

    def check_api_performance(self) -> Dict[str, float]:
        """
        API 성능 체크

        Returns:
            성능 지표 dict
        """
        if not self.results:
            return {}

        durations = [r.duration for r in self.results]

        return {
            'min_time': min(durations),
            'max_time': max(durations),
            'avg_time': sum(durations) / len(durations),
            'p95_time': sorted(durations)[int(len(durations) * 0.95)] if durations else 0,
        }

    def get_failed_scenarios(self) -> List[TestResult]:
        """실패한 시나리오만 조회"""
        return [r for r in self.results if r.status == "FAIL"]

    def get_warning_scenarios(self) -> List[TestResult]:
        """경고 시나리오만 조회"""
        return [r for r in self.results if r.status == "WARNING"]
