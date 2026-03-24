import json
from datetime import datetime, timedelta
import anthropic
from config import ANTHROPIC_API_KEY, TIMEZONE
import pytz

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
tz = pytz.timezone(TIMEZONE)


def now_kst() -> datetime:
    return datetime.now(tz)


TOOLS = [
    {
        "name": "create_event",
        "description": "Google Calendar에 새 일정을 생성합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title":       {"type": "string", "description": "일정 제목"},
                "start":       {"type": "string", "description": "시작 일시 (ISO8601, 예: 2026-03-21T15:00:00)"},
                "end":         {"type": "string", "description": "종료 일시 (ISO8601)"},
                "location":    {"type": "string", "description": "장소 (선택)"},
                "description": {"type": "string", "description": "설명/메모 (선택)"},
                "attendees":   {"type": "array", "items": {"type": "string"}, "description": "참석자 이메일 목록 (선택)"},
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
        "description": "지정한 날에 비어있는 시간대를 찾습니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date":         {"type": "string", "description": "날짜 (ISO8601 날짜, 예: 2026-03-21)"},
                "duration_hours":{"type": "number", "description": "필요한 여유 시간 (시간 단위)"},
            },
            "required": ["date"],
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
"""


async def parse_intent(user_message: str, history: list[dict] = None) -> dict:
    """
    사용자 메시지를 분석해 tool call 결과를 반환합니다.
    반환: {"tool": str, "args": dict} 또는 {"tool": "plain_reply", "args": {"message": str}}
    """
    messages = []
    if history:
        messages.extend(history[-6:])  # 최근 3턴 유지
    messages.append({"role": "user", "content": user_message})

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=build_system_prompt(),
        tools=TOOLS,
        messages=messages,
    )

    for block in response.content:
        if block.type == "tool_use":
            return {"tool": block.name, "args": block.input}

    # tool_use가 없으면 텍스트 응답 반환
    text = next((b.text for b in response.content if hasattr(b, "text")), "")
    return {"tool": "plain_reply", "args": {"message": text}}
