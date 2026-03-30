"""
Claude API 결과 단기 캐시 (인메모리, 30초 TTL)

캐시 대상: 읽기 전용 intent (list_events, find_free_slots)
캐시 제외: create_event, delete_event, set_reminder (쓰기 작업)

목적: 같은 사용자가 짧은 시간 안에 동일 질문을 반복할 때 API 재호출 방지
"""
import hashlib
import time
from typing import Optional

_CACHE: dict[str, tuple[list, float]] = {}
_TTL = 30  # 초

# 캐시하지 않는 도구 목록 (쓰기 작업)
_NO_CACHE_TOOLS = {"create_event", "delete_event", "set_reminder"}


def _key(uid: int, message: str) -> str:
    normalized = message.strip().lower()
    return hashlib.md5(f"{uid}:{normalized}".encode()).hexdigest()


def get(uid: int, message: str) -> Optional[list]:
    """캐시 히트 시 결과 반환, 미스 시 None."""
    k = _key(uid, message)
    entry = _CACHE.get(k)
    if entry is None:
        return None
    result, expires_at = entry
    if time.monotonic() > expires_at:
        del _CACHE[k]
        return None
    return result


def put(uid: int, message: str, result: list) -> None:
    """읽기 전용 결과만 캐시에 저장."""
    if not result:
        return
    # 하나라도 쓰기 도구가 있으면 캐시 안 함
    if any(r["tool"] in _NO_CACHE_TOOLS for r in result):
        return
    _purge_expired()
    _CACHE[_key(uid, message)] = (result, time.monotonic() + _TTL)


def _purge_expired() -> None:
    now = time.monotonic()
    expired = [k for k, (_, exp) in _CACHE.items() if now > exp]
    for k in expired:
        del _CACHE[k]
