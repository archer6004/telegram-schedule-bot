"""
팀 일정 충돌 감지 및 해결 서비스

우선순위 규칙:
  🔴 red   = 필수    (변경 불가)
  🟡 yellow = 조율가능 (협의 요청)
  🟢 green  = 자유    (알림만)

충돌 해결 매트릭스:
  신규 🔴 vs 기존 🟡/🟢 → 기존 측에 조율 요청 알림
  신규 🔴 vs 기존 🔴    → 관리자에게 에스컬레이션
  신규 🟡 vs 기존 🟡    → 양측에 조율 요청, 먼저 수락한 쪽 유지
  신규 🟡/🟢 vs 기존 🔴 → 신규 일정 등록 차단 + 안내
  신규 🟢 vs 기존 🟡/🟢 → 알림만 (등록은 허용)
"""
import logging
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton

import db as db
from services.calendar_service import list_events

log = logging.getLogger(__name__)

PRIORITY_LABEL = {
    "red":    "🔴 필수",
    "yellow": "🟡 조율가능",
    "green":  "🟢 자유",
}


def check_conflicts(start_dt: str, end_dt: str,
                    exclude_uid: int | None = None) -> list[dict]:
    """
    두 가지 소스에서 start_dt~end_dt 겹치는 일정 검사.
      1) team_events DB — 기존 팀 일정
      2) Google Calendar — 연동 사용자의 개인 일정 (종일 이벤트 제외)

    반환: [{"uid": int, "name": str, "events": list, "priority": str}]
    """
    conflicts: list[dict] = []
    seen_uids: set[int] = set()

    # ── 1. 팀 이벤트 DB 충돌 검사 ──────────────────────────────
    # exclude_uid 없이 전체 검색 — 본인이 등록한 팀 이벤트와의 중복도 감지
    existing_team = db.get_overlapping_team_events(start_dt, end_dt, exclude_uid=None)
    for te in existing_team:
        organizer = te["organizer_id"]
        seen_uids.add(organizer)
        conflicts.append({
            "uid":      organizer,
            "name":     te.get("organizer_name") or f"user_{organizer}",
            "events":   [],
            "priority": te["priority"],
            "is_self":  organizer == exclude_uid,  # 본인이 등록한 팀 이벤트 여부
        })
        log.debug("팀 이벤트 DB 충돌: uid=%s is_self=%s title=%s priority=%s",
                  organizer, organizer == exclude_uid, te.get("title"), te["priority"])

    # ── 2. Google Calendar 충돌 검사 (연동 사용자 전원, 등록자 포함) ───
    # 등록자 본인 캘린더도 검사 — 본인 일정과 겹치면 is_self=True 마킹
    users = db.get_all_connected_users()
    for user in users:
        uid = user["telegram_id"]
        if uid in seen_uids:
            continue
        try:
            events = list_events(uid, start_dt, end_dt)
            # 종일 이벤트(all-day)는 프레임 이벤트 → 충돌 감지에서 제외
            timed_events = [e for e in events if "dateTime" in e.get("start", {})]
            if timed_events:
                conflicts.append({
                    "uid":      uid,
                    "name":     user["full_name"] or f"user_{uid}",
                    "events":   timed_events,
                    "priority": "yellow",
                    "is_self":  uid == exclude_uid,  # 등록자 본인 충돌 여부
                })
                log.debug("Google Cal 충돌 감지: uid=%s is_self=%s count=%d",
                          uid, uid == exclude_uid, len(timed_events))
        except Exception as e:
            log.warning("충돌 검사 실패 uid=%s: %s", uid, e)

    return conflicts


def resolve_rule(new_priority: str, existing_priority: str) -> str:
    """
    반환값:
      'block'     - 신규 일정 등록 차단
      'escalate'  - 관리자 에스컬레이션
      'negotiate' - 양측 조율 요청
      'notify'    - 알림만 (등록 허용)
    """
    rank = {"red": 3, "yellow": 2, "green": 1}
    n = rank.get(new_priority, 2)
    e = rank.get(existing_priority, 2)

    if n == 3 and e == 3:   # 🔴 vs 🔴
        return "escalate"
    if n == 3 and e < 3:    # 🔴 vs 🟡/🟢
        return "negotiate"
    if n < 3 and e == 3:    # 🟡/🟢 vs 🔴
        return "block"
    if n == 2 and e == 2:   # 🟡 vs 🟡
        return "negotiate"
    return "notify"         # 🟢 관련


async def handle_conflicts(
    bot: Bot,
    team_event_id: int,
    new_priority: str,
    conflicts: list[dict],
    admin_ids: list[int],
) -> dict:
    """
    충돌 처리 후 결과 반환.
    반환: {"blocked": bool, "escalated": bool, "notified": list[str]}
    """
    result = {"blocked": False, "escalated": False, "notified": []}
    event = db.get_team_event(team_event_id)

    for c in conflicts:
        uid   = c["uid"]
        name  = c["name"]
        evts  = c["events"]
        their_priority = c.get("priority", "yellow")  # check_conflicts()가 설정한 실제 우선순위

        action = resolve_rule(new_priority, their_priority)
        conflict_id = db.add_conflict(team_event_id, uid, their_priority)

        # 프라이버시 정책: 상대방 일정 제목·시간은 노출하지 않음
        # 사용자명만 공개하여 조율 진행
        title    = event["title"]
        start    = event["start_dt"][:16].replace("T", " ")
        end      = event["end_dt"][:16].replace("T", " ")
        new_lbl  = PRIORITY_LABEL.get(new_priority, new_priority)
        their_lbl = PRIORITY_LABEL.get(their_priority, their_priority)

        if action == "block":
            result["blocked"] = True

        elif action == "escalate":
            result["escalated"] = True
            db.resolve_conflict(conflict_id, "escalated")
            for admin_id in admin_ids:
                try:
                    await bot.send_message(
                        chat_id=admin_id,
                        text=(
                            f"⚠️ *팀 일정 충돌 — 관리자 조율 필요*\n\n"
                            f"새 일정: *{title}*\n"
                            f"일시: {start} ~ {end}\n"
                            f"충돌 담당자: {name}\n"
                            f"양쪽 모두 {new_lbl} 로 등록됨\n\n"
                            f"각 담당자의 캘린더를 직접 확인 후 조율해 주세요."
                        ),
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass

        elif action == "negotiate":
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "✅ 내 일정 조율 가능", callback_data=f"conflict_accept:{conflict_id}"),
                InlineKeyboardButton(
                    "❌ 내 일정 변경 불가", callback_data=f"conflict_decline:{conflict_id}"),
            ]])
            try:
                await bot.send_message(
                    chat_id=uid,
                    text=(
                        f"📅 *팀 일정 충돌 알림*\n\n"
                        f"*{title}* 일정이 귀하의 캘린더와 충돌합니다.\n"
                        f"충돌 시간대: {start} ~ {end}\n"
                        f"신규 일정 중요도: {new_lbl}\n\n"
                        f"해당 시간대에 귀하의 일정이 있습니다.\n"
                        f"조율 가능 여부를 알려주세요."
                    ),
                    parse_mode="Markdown",
                    reply_markup=kb,
                )
                result["notified"].append(name)
            except Exception as e:
                log.warning("조율 알림 실패 uid=%s: %s", uid, e)

        elif action == "notify":
            db.resolve_conflict(conflict_id, "accepted")
            try:
                await bot.send_message(
                    chat_id=uid,
                    text=(
                        f"📅 *팀 일정 등록 알림*\n\n"
                        f"*{title}* 일정이 등록됐습니다.\n"
                        f"일시: {start} ~ {end}\n\n"
                        f"해당 시간대에 귀하의 일정과 시간이 겹칩니다.\n"
                        f"필요 시 캘린더를 직접 확인해 주세요."
                    ),
                    parse_mode="Markdown",
                )
                result["notified"].append(name)
            except Exception as e:
                log.warning("알림 실패 uid=%s: %s", uid, e)

    return result


def _infer_priority(events: list) -> str:
    """기존 일정에서 우선순위 추정 (기본 yellow)."""
    return "yellow"


def _fmt_time(dt_obj: dict) -> str:
    val = dt_obj.get("dateTime", dt_obj.get("date", ""))
    return val[11:16] if "T" in val else val
