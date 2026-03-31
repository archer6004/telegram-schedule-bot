"""
Log Collector

bot.log에서 테스트 관련 정보 수집
"""

import logging
import os
from typing import List, Dict, Optional
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class LogCollector:
    """bot.log 분석 및 정보 수집"""

    def __init__(self, log_file_path: str):
        """
        Args:
            log_file_path: bot.log 파일 경로
        """
        self.log_file_path = log_file_path
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None

    def set_time_window(self, start_time: datetime, end_time: datetime):
        """테스트 시간 범위 설정"""
        self.start_time = start_time
        self.end_time = end_time

    def read_log_file(self) -> List[str]:
        """로그 파일 읽기"""
        try:
            if not os.path.exists(self.log_file_path):
                logger.warning(f"로그 파일 없음: {self.log_file_path}")
                return []

            with open(self.log_file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            return lines
        except Exception as e:
            logger.error(f"로그 파일 읽기 실패: {e}")
            return []

    def extract_errors(self, lines: List[str] = None) -> List[str]:
        """
        로그에서 ERROR/Exception 추출

        Args:
            lines: 로그 라인 리스트 (None이면 파일에서 읽음)

        Returns:
            에러 메시지 리스트
        """
        if lines is None:
            lines = self.read_log_file()

        errors = []
        for line in lines:
            if self._in_time_window(line):
                if 'ERROR' in line or 'Exception' in line or 'Traceback' in line:
                    errors.append(line.strip())

        return errors

    def extract_warnings(self, lines: List[str] = None) -> List[str]:
        """
        로그에서 WARNING 추출

        Args:
            lines: 로그 라인 리스트

        Returns:
            경고 메시지 리스트
        """
        if lines is None:
            lines = self.read_log_file()

        warnings = []
        for line in lines:
            if self._in_time_window(line):
                if 'WARNING' in line:
                    warnings.append(line.strip())

        return warnings

    def extract_api_calls(self, lines: List[str] = None) -> Dict[str, int]:
        """
        API 호출 통계

        Args:
            lines: 로그 라인 리스트

        Returns:
            {API 타입: 횟수} 매핑
        """
        if lines is None:
            lines = self.read_log_file()

        api_counts = {}
        for line in lines:
            if self._in_time_window(line):
                if 'HTTP Request' in line:
                    # "POST /getMe" 또는 "POST /sendMessage" 등 추출
                    parts = line.split('"')
                    if len(parts) >= 2:
                        api = parts[1]  # "POST /getMe"
                        api_counts[api] = api_counts.get(api, 0) + 1

        return api_counts

    def extract_response_times(self, lines: List[str] = None) -> List[float]:
        """
        응답 시간 추출 (초)

        Args:
            lines: 로그 라인 리스트

        Returns:
            응답 시간 리스트
        """
        if lines is None:
            lines = self.read_log_file()

        response_times = []
        for line in lines:
            if self._in_time_window(line):
                if 'HTTP Request' in line and 'HTTP/1.1' in line:
                    # 예: "HTTP Request: POST ... (took 0.234s)" 형식이면 추출
                    # 현재 로그 포맷에는 시간 정보가 없으므로 pass
                    pass

        return response_times

    def extract_mentions(self, keyword: str, lines: List[str] = None) -> List[str]:
        """
        특정 키워드 언급 추출

        Args:
            keyword: 검색 키워드
            lines: 로그 라인 리스트

        Returns:
            매칭된 라인 리스트
        """
        if lines is None:
            lines = self.read_log_file()

        mentions = []
        for line in lines:
            if self._in_time_window(line):
                if keyword.lower() in line.lower():
                    mentions.append(line.strip())

        return mentions

    def _in_time_window(self, line: str) -> bool:
        """
        라인이 시간 범위 내에 있는지 확인

        로그 형식: "2026-03-31 09:21:19,272 [INFO]..."
        """
        if not self.start_time or not self.end_time:
            return True  # 시간 범위 미설정이면 모든 라인 포함

        try:
            # 로그 라인의 타임스탬프 추출
            timestamp_str = line[:19]  # "2026-03-31 09:21:19"
            line_time = datetime.fromisoformat(timestamp_str)

            return self.start_time <= line_time <= self.end_time
        except Exception:
            return False

    def generate_summary(self) -> Dict:
        """
        로그 요약 생성

        Returns:
            {에러 개수, 경고 개수, API 호출 수, ...}
        """
        lines = self.read_log_file()

        errors = self.extract_errors(lines)
        warnings = self.extract_warnings(lines)
        api_calls = self.extract_api_calls(lines)

        total_api_calls = sum(api_calls.values())

        return {
            "error_count": len(errors),
            "warning_count": len(warnings),
            "api_call_count": total_api_calls,
            "api_breakdown": api_calls,
            "errors": errors[-5:],  # 최근 5개만
            "warnings": warnings[-5:],  # 최근 5개만
        }
