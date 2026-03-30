"""
프로젝트 전역 상수
- ctx.user_data 키는 반드시 이 파일에서 가져와 사용하세요.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[PROTECTED MODULE] — 수정 전 반드시 사용자 승인 필요
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
이 파일의 상수는 여러 핸들러가 공유합니다.
이름 변경·삭제 시 아래 파일 전체를 동시에 수정해야 합니다:

  KEY_HISTORY               → handlers/calendar_handler.py
  KEY_TEAM_INPUT_MODE       → handlers/calendar_handler.py
  KEY_PENDING_TEAM_EVENT    → handlers/calendar_handler.py
                               handlers/team_handler.py
  SENTINEL_PRIORITY_BUTTONS → handlers/calendar_handler.py
  STATUS_ICON               → handlers/admin_handler.py

수정이 필요할 경우: 변경 내용과 영향 범위를 사용자에게 상세히
설명하고 승인을 받은 후 관련 파일을 모두 함께 수정할 것.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

# ── ctx.user_data 키 ──────────────────────────────────────
KEY_HISTORY           = "history"
KEY_TEAM_INPUT_MODE   = "team_input_mode"
KEY_PENDING_TEAM_EVENT = "pending_team_event"

# ── 팀 일정 sentinel ──────────────────────────────────────
SENTINEL_PRIORITY_BUTTONS = "__PRIORITY_BUTTONS__"

# ── 사용자 상태 아이콘 ────────────────────────────────────
STATUS_ICON = {
    "APPROVED":  "✅",
    "PENDING":   "⏳",
    "REJECTED":  "❌",
    "SUSPENDED": "🚫",
}
