import asyncio
import json
import re
from datetime import datetime, timedelta
import anthropic
from config import ANTHROPIC_API_KEY, TIMEZONE, CLAUDE_TIMEOUT_SEC
import pytz

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
tz = pytz.timezone(TIMEZONE)

HAIKU_MODEL  = "claude-haiku-4-5-20251001"
SONNET_MODEL = "claude-sonnet-4-6"

# Haiku가 plain_reply를 반환했지만 캘린더 관련 키워드가 있으면 Sonnet으로 에스컬레이션
_CALENDAR_KEYWORDS = re.compile(
    r"일정|등록|추가|잡아|취소|삭제|리마인더|알림|빈\s*시간|비는\s*시간|보여줘|찾아줘|스케줄"
)


def now_kst() -> datetime:
    return datetime.now(tz)


TOOLS = [
    {
        "name": "create_event",
        "description": "Google Calendar에 새 일정을 생성합니다. 팀 회의·공용 일정이면 is_team=true로 설정하세요.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title":       {"type": "string", "description": "일정 제목"},
                "start":       {"type": "string", "description": "시작 일시 (ISO8601, 예: 2026-03-21T15:00:00)"},
                "end":         {"type": "string", "description": "종료 일시 (ISO8601)"},
                "location":    {"type": "string", "description": "장소 (선택)"},
                "description": {"type": "string", "description": "설명/메모 (선택)"},
                "attendees":   {"type": "array", "items": {"type": "string"}, "description": "참석자 이메일 목록 (선택)"},
                "is_team":     {"type": "boolean", "description": "팀 공용 일정 여부 (팀·회의·공용 키워드 시 true)"},
            },
            "required": ["title", "start", "end"],
        },
    },
    {
        "name": "list_events",
        "description": "기간 내 Google Calendar 일정 목록을 조회합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "time_min": {"type": "string", "description": "조회 시작 일시 (ISO8601)"},
                "time_max": {"type": "string", "description": "조회 종료 일시 (ISO8601)"},
            },
            "required": ["time_min", "time_max"],
        },
    },
    {
        "name": "list_team_events",
        "description": "팀 일정 DB에서 기간 내 팀 이벤트 목록을 조회합니다. '팀 일정', '팀 회의', '팀 스케줄' 등 팀 관련 조회에 사용하세요.",
        "input_schema": {
            "type": "object",
            "properties": {
                "time_min": {"type": "string", "description": "조회 시작 날짜 (ISO8601, 예: 2026-04-01)"},
                "time_max": {"type": "string", "description": "조회 종료 날짜 (ISO8601, 예: 2026-04-30)"},
            },
            "required": ["time_min", "time_max"],
        },
    },
    {
        "name": "delete_event",
        "description": "제목이나 날짜 힌트를 기반으로 일정을 삭제합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query":    {"type": "string", "description": "삭제할 일정 제목 키워드"},
                "date_hint":{"type": "string", "description": "일정 날짜 힌트 (ISO8601 날짜)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "find_free_slots",
        "description": "지정한 날짜 범위에서 비어있는 시간대를 찾습니다. 단일 날짜면 date_from=date_to로 설정하세요.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date_from":     {"type": "string", "description": "검색 시작 날짜 (ISO8601, 예: 2026-04-07)"},
                "date_to":       {"type": "string", "description": "검색 종료 날짜 (ISO8601, 예: 2026-04-11)"},
                "duration_hours":{"type": "number", "description": "필요한 연속 여유 시간 (시간 단위, 예: 7)"},
            },
            "required": ["date_from", "date_to"],
        },
    },
    {
        "name": "set_reminder",
        "description": "특정 일정에 리마인더를 설정합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_query":      {"type": "string", "description": "일정 제목 키워드"},
                "minutes_before":   {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "몇 분 전에 알릴지 (예: [60, 10])"
                },
            },
            "required": ["event_query", "minutes_before"],
        },
    },
    {
        "name": "plain_reply",
        "description": "캘린더 액션 없이 일반 텍스트로 응답합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "사용자에게 보낼 메시지"},
            },
            "required": ["message"],
        },
    },
]


def build_system_prompt() -> str:
    now = now_kst()
    return f"""당신은 Google Calendar를 관리해주는 스케줄 어시스턴트입니다.
현재 날짜/시각: {now.strftime('%Y년 %m월 %d일 (%A) %H:%M')} (KST)

규칙:
1. 사용자의 자연어 요청을 분석해 적절한 tool을 반드시 호출하세요.
2. 날짜/시간이 모호하면 현재 시각 기준으로 합리적으로 추론하세요.
   - "내일" → 내일 날짜, "이번 주" → 이번 주 월~일
3. 일정 종료 시각이 명시되지 않으면 시작+1시간으로 설정하세요.
4. 캘린더와 무관한 질문은 plain_reply로 친절하게 안내하세요.
5. 항상 한국어로 응답하세요.
6. 팀·전체·공용·회의 등 여러 사람이 관련된 일정은 반드시 is_team=true로 설정하세요.
   예: "팀 회의", "전체 미팅", "팀 일정으로 잡아줘", "공용 일정"
7. "5/1부터 5/5까지 매일 오전 9시" 처럼 날짜 범위에 걸친 일정은
   날짜마다 create_event를 각각 호출하세요. 하나의 응답에 여러 tool_use를 포함해도 됩니다.
8. "여행", "출장", "휴가" 등 종일(all-day) 이벤트는 프레임 일정입니다.
   그 안에 세부 일정(관광지 방문 등)을 넣을 수 있으며, 빈 시간 계산과 충돌 감지에서 제외됩니다.
   사용자가 종일 일정 안에 세부 일정을 추가하려 하면 자연스럽게 안내해 주세요.
"""


async def parse_intent(user_message: str, history: list[dict] = None) -> list[dict]:
    """
    사용자 메시지를 분석해 tool call 결과 목록을 반환합니다.
    반환: [{"tool": str, "args": dict}, ...] — 여러 tool_use 모두 포함
    tool_use가 없으면 [{"tool": "plain_reply", "args": {"message": str}}]

    2-stage 전략:
      1차) Haiku  — 빠르고 저렴 (~25x)
      2차) Sonnet — Haiku가 plain_reply를 반환했지만 캘린더 키워드가 있을 때만 에스컬레이션
    """
    messages = []
    if history:
        messages.extend(history[-6:])  # 최근 3턴 유지
    messages.append({"role": "user", "content": user_message})

    def _call(model: str) -> list[dict]:
        """동기 SDK 호출 (asyncio.to_thread 에서 실행)."""
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=build_system_prompt(),
            tools=TOOLS,
            messages=messages,
        )
        intents = [
            {"tool": block.name, "args": block.input}
            for block in response.content
            if block.type == "tool_use"
        ]
        if intents:
            return intents
        text = next((b.text for b in response.content if hasattr(b, "text")), "")
        return [{"tool": "plain_reply", "args": {"message": text}}]

    # asyncio.to_thread: 동기 SDK 호출을 별도 스레드에서 실행
    # → Telegram 이벤트 루프 블로킹 방지 (2~5초 대기 동안 다른 사용자 처리 가능)
    # asyncio.wait_for: CLAUDE_TIMEOUT_SEC 초 내 응답 없으면 TimeoutError
    result = await asyncio.wait_for(
        asyncio.to_thread(_call, HAIKU_MODEL),
        timeout=CLAUDE_TIMEOUT_SEC,
    )

    # 에스컬레이션: plain_reply 이지만 캘린더 키워드가 포함된 경우 Sonnet으로 재시도
    if (
        len(result) == 1
        and result[0]["tool"] == "plain_reply"
        and _CALENDAR_KEYWORDS.search(user_message)
    ):
        result = await asyncio.wait_for(
            asyncio.to_thread(_call, SONNET_MODEL),
            timeout=CLAUDE_TIMEOUT_SEC,
        )

    return result
