"""
공통 유틸리티

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[PROTECTED MODULE] — 수정 전 반드시 사용자 승인 필요
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
이 파일은 보안 관련 핵심 기능을 담당합니다.

  escape_md()            → Markdown 삽입 시 XSS 방지
                           사용: handlers/admin_handler.py
                           규칙: 이스케이프 문자 패턴 변경 금지

  generate_oauth_state() → Google OAuth 보안 토큰 생성
  resolve_oauth_state()  → 토큰 검증 및 uid 반환
                           사용: handlers/auth_handler.py,
                                 handlers/calendar_handler.py
                           규칙: 두 함수는 반드시 쌍으로 동작해야 함.
                                 한쪽만 수정하면 구글 로그인 전체 불가.
                                 _STATE_TTL(600초) 변경 시 보안 영향 검토 필요.

수정이 필요할 경우: 변경 내용과 보안 영향을 사용자에게 상세히
설명하고 승인을 받은 후 관련 파일을 모두 함께 수정할 것.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import re
import secrets
import time
from typing import Optional


# ── Markdown 이스케이프 ───────────────────────────────────

def escape_md(text: str) -> str:
    """
    Telegram Markdown v1 특수문자를 이스케이프합니다.
    사용자 이름, 일정 제목 등 외부 입력을 Markdown 메시지에 삽입할 때 사용하세요.

    이스케이프 대상: _ * ` [
    """
    return re.sub(r'([_*`\[])', r'\\\1', str(text))


# ── OAuth state 관리 (인메모리, TTL 10분) ────────────────

_STATE_STORE: dict[str, tuple[int, float]] = {}  # state → (uid, expires_at)
_STATE_TTL = 600  # 10분


def generate_oauth_state(uid: int) -> str:
    """
    예측 불가능한 랜덤 state 생성 후 uid와 매핑하여 저장합니다.
    기존 방식(state=telegram_id)은 URL에 uid가 노출되는 문제가 있었습니다.
    """
    _purge_expired_states()
    state = secrets.token_urlsafe(16)
    _STATE_STORE[state] = (uid, time.monotonic() + _STATE_TTL)
    return state


def resolve_oauth_state(state: str) -> Optional[int]:
    """state로 uid를 조회합니다. 만료됐거나 없으면 None 반환."""
    entry = _STATE_STORE.pop(state, None)
    if entry is None:
        return None
    uid, expires_at = entry
    if time.monotonic() > expires_at:
        return None
    return uid


def _purge_expired_states() -> None:
    """만료된 state 항목을 정리합니다."""
    now = time.monotonic()
    expired = [s for s, (_, exp) in _STATE_STORE.items() if now > exp]
    for s in expired:
        del _STATE_STORE[s]
