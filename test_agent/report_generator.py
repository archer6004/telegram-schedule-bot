"""
Test Report Generator

테스트 리포트 생성
"""

import logging
from datetime import datetime
from typing import List
from test_agent.analyzer import TestSummary, TestResult

logger = logging.getLogger(__name__)


class ReportGenerator:
    """테스트 리포트 생성기"""

    def __init__(self):
        self.timestamp = datetime.now()

    def generate_summary_report(self, summary: TestSummary, results: List[TestResult], duration_minutes: float = 0) -> str:
        """
        요약 리포트 생성 (채팅용)

        Args:
            summary: TestSummary 객체
            results: TestResult 리스트
            duration_minutes: 실행 소요 시간 (분)

        Returns:
            마크다운 형식의 리포트
        """
        time_str = self.timestamp.strftime("%Y-%m-%d %H:%M")

        # 상태 이모지
        if summary.pass_rate == 100:
            status_emoji = "🟢"
        elif summary.pass_rate >= 80:
            status_emoji = "🟡"
        else:
            status_emoji = "🔴"

        report = f"""🤖 일일 테스트 리포트 ({time_str})

{status_emoji} **테스트 결과**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ PASS: {summary.passed}/{summary.total} ({summary.pass_rate:.1f}%)
⚠️ WARNING: {summary.warnings}건
❌ FAIL: {summary.failed}건

📊 **성능 지표**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⏱️ 평균 응답시간: {summary.avg_response_time*1000:.0f}ms
⏱️ 총 소요시간: {summary.total_duration:.1f}초
"""

        # 실패/경고 상세
        if summary.failed > 0:
            report += f"\n❌ **실패한 테스트**\n"
            failed_results = [r for r in results if r.status == "FAIL"]
            for result in failed_results[:5]:  # 최대 5개만
                report += f"- {result.scenario_name}\n"
                if result.error_message:
                    report += f"  `{result.error_message[:50]}...`\n"

        if summary.warnings > 0:
            report += f"\n⚠️ **경고**\n"
            warning_results = [r for r in results if r.status == "WARNING"]
            for result in warning_results[:3]:  # 최대 3개만
                report += f"- {result.scenario_name}\n"

        # 개선 제안
        if summary.suggestions:
            report += f"\n💡 **개선 제안**\n"
            for suggestion in summary.suggestions[:3]:  # 최대 3개만
                report += f"{suggestion}\n"

        # 상세 정보 링크
        report += f"\n📎 *상세 리포트는 로그 참고*\n"

        return report

    def generate_detailed_report(self, summary: TestSummary, results: List[TestResult]) -> str:
        """
        상세 리포트 생성 (파일용)

        Args:
            summary: TestSummary 객체
            results: TestResult 리스트

        Returns:
            마크다운 형식의 상세 리포트
        """
        report = f"""# 테스트 리포트

**생성 시간**: {self.timestamp.strftime("%Y-%m-%d %H:%M:%S")}

## 📊 전체 결과

| 항목 | 수치 | 비율 |
|------|------|------|
| 전체 | {summary.total} | 100% |
| ✅ 통과 | {summary.passed} | {summary.pass_rate:.1f}% |
| ⚠️ 경고 | {summary.warnings} | {(summary.warnings/summary.total*100):.1f}% |
| ❌ 실패 | {summary.failed} | {(summary.failed/summary.total*100):.1f}% |

## ⏱️ 성능

- **총 소요시간**: {summary.total_duration:.2f}초
- **평균 응답시간**: {summary.avg_response_time*1000:.0f}ms
- **최소**: {min(r.duration for r in results)*1000:.0f}ms
- **최대**: {max(r.duration for r in results)*1000:.0f}ms

## 📋 상세 결과

"""
        # 각 테스트 결과
        for result in results:
            status_icon = "✅" if result.status == "PASS" else "⚠️" if result.status == "WARNING" else "❌"
            report += f"""### {status_icon} {result.scenario_name}

- **ID**: {result.scenario_id}
- **상태**: {result.status}
- **소요시간**: {result.duration:.2f}초
"""
            if result.error_message:
                report += f"- **에러**: {result.error_message}\n"

            if result.log_excerpt:
                report += f"- **로그**:\n```\n{result.log_excerpt}\n```\n"

            report += "\n"

        # 에러 요약
        if summary.errors:
            report += "## 🚨 에러 요약\n\n"
            for i, error in enumerate(summary.errors[:10], 1):
                report += f"{i}. {error}\n"

        # 개선 제안
        if summary.suggestions:
            report += "\n## 💡 개선 제안\n\n"
            for suggestion in summary.suggestions:
                report += f"- {suggestion}\n"

        return report

    def generate_short_summary(self, summary: TestSummary) -> str:
        """
        극단적으로 짧은 요약 (1줄)

        Args:
            summary: TestSummary 객체

        Returns:
            한 줄 요약
        """
        emoji = "✅" if summary.pass_rate == 100 else "⚠️" if summary.pass_rate >= 80 else "❌"
        return f"{emoji} 테스트: {summary.passed}/{summary.total} 통과 ({summary.pass_rate:.0f}%) - {summary.total_duration:.1f}초"
