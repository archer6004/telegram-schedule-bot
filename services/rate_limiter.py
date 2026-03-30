"""
사용자별 Claude API 호출 횟수 제한 (슬라이딩 윈도우 방식, 인메모리)
"""
import time
from collections import defaultdict, deque
from config import RATE_LIMIT_CALLS, RATE_LIMIT_PERIOD


# uid → deque[timestamp]
_buckets: dict[int, deque] = defaultdict(deque)


def is_allowed(uid: int) -> bool:
    """
    True  → 호출 허용 (카운터 증가)
    False → 한도 초과, 거부
    """
    now = time.monotonic()
    bucket = _buckets[uid]

    # 윈도우 밖의 오래된 항목 제거
    while bucket and now - bucket[0] > RATE_LIMIT_PERIOD:
        bucket.popleft()

    if len(bucket) >= RATE_LIMIT_CALLS:
        return False

    bucket.append(now)
    return True


def remaining(uid: int) -> int:
    """현재 윈도우 내 남은 호출 횟수."""
    now = time.monotonic()
    bucket = _buckets[uid]
    while bucket and now - bucket[0] > RATE_LIMIT_PERIOD:
        bucket.popleft()
    return max(0, RATE_LIMIT_CALLS - len(bucket))
