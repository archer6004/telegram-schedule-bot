"""
팀 일정 우선순위 선택 + 충돌 해결 핸들러

흐름:
1. Claude가 create_event(is_team=true) 반환
2. calendar_handler가 priority_pending 상태로 저장 후 우선순위 버튼 전송
3. 사용자가 🔴/🟡/🟢 탭
4. team_service가 충돌 검사 → 결과에 따라 등록/차단/협의 알림
5. 충돌 상대방이 accept/decline 탭 → 알림 전송
"""
import logging
from datetime import datetime
import pytz
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CallbackQueryHandler

logger = logging.getLogger(__name__)

import db as db
from services import team_service
from services.calendar_service import create_event, write_to_shared_calendar
from services.scheduler_service import schedule_reminders_for_event
from config import ADMIN_TELEGRAM_IDS, DEFAULT_REMINDER_MINUTES, TIMEZONE
from constants import KEY_PENDING_TEAM_EVENT

_tz = pytz.timezone(TIMEZONE)

PRIORITY_BUTTONS = InlineKeyboardMarkup([[
    InlineKeyboardButton("🔴 필수",     callback_data="priority:red"),
    InlineKeyboardButton("🟡 조율가능", callback_data="priority:yellow"),
    InlineKeyboardButton("🟢 자유",     callback_data="priority:green"),
]])


async def priority_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """우선순위 버튼 탭 처리."""
    query = update.callback_query
    await query.answer()
    priority = query.data.split(":")[1]          # red / yellow / green
    uid      = query.from_user.id

    # calendar_handler가 ctx.user_data에 저장한 대기 중인 팀 이벤트 정보
    pending = ctx.user_data.pop(KEY_PENDING_TEAM_EVENT, None)
    if not pending:
        await query.edit_message_text("⚠️ 일정 정보가 만료됐습니다. 다시 말씀해 주세요.")
        return

    title = pending["title"]
    start = pending["start"]
    end   = pending["end"]
    label = team_service.PRIORITY_LABEL[priority]

    await query.edit_message_text(f"🔍 *{label}* 로 충돌 검사 중...", parse_mode="Markdown")

    # ── 1. 충돌 검사 (등록 전에 먼저) ───────────────────────────
    conflicts = team_service.check_conflicts(start, end, exclude_uid=uid)

    self_conflicts  = [c for c in conflicts if c.get("is_self")]
    other_conflicts = [c for c in conflicts if not c.get("is_self")]

    # 본인 팀 이벤트 중복 → 등록 차단
    self_team_conflicts = [c for c in self_conflicts if not c.get("events")]  # DB 출처 = 팀 이벤트
    if self_team_conflicts:
        await ctx.bot.send_message(
            chat_id=uid,
            text=(
                f"🚫 *{title}* 등록 불가\n\n"
                f"해당 시간대에 이미 등록한 팀 일정이 있습니다.\n"
                f"일정 시간을 변경하거나 기존 팀 일정을 취소해 주세요."
            ),
            parse_mode="Markdown",
        )
        return  # 등록하지 않음

    # 본인 Google Calendar 충돌 → 경고만 (개인 일정과 팀 일정 병행 허용)
    self_cal_conflicts = [c for c in self_conflicts if c.get("events")]
    if self_cal_conflicts:
        await ctx.bot.send_message(
            chat_id=uid,
            text=(
                f"⚠️ *주의*: 해당 시간대에 개인 일정이 있습니다.\n"
                f"팀 일정은 계속 등록됩니다."
            ),
            parse_mode="Markdown",
        )

    # 타인 충돌 중 block 조건 → 등록 차단
    for c in other_conflicts:
        action = team_service.resolve_rule(priority, c.get("priority", "yellow"))
        if action == "block":
            await ctx.bot.send_message(
                chat_id=uid,
                text=(
                    f"🚫 *{title}* 등록 불가\n\n"
                    f"해당 시간대에 *{c['name']}* 님의 "
                    f"{team_service.PRIORITY_LABEL['red']} 일정이 있습니다.\n"
                    f"일정 시간을 변경해 주세요."
                ),
                parse_mode="Markdown",
            )
            return  # 등록하지 않음

    # ── 2. block 없음 → 본인 캘린더에 일정 등록 ─────────────────
    try:
        event = create_event(
            uid, title, start, end,
            location=pending.get("location", ""),
            description=pending.get("description", ""),
            attendees=pending.get("attendees", []),
        )
        google_event_id = event.get("id", "") if isinstance(event, dict) else ""
    except PermissionError as e:
        await ctx.bot.send_message(chat_id=uid, text=str(e))
        return
    except Exception as e:
        await ctx.bot.send_message(
            chat_id=uid, text=f"❌ 일정 등록 실패: {e}")
        return

    # 리마인더 스케줄링 (위저드에서 설정한 경우 사용, 없으면 기본값)
    reminder_minutes = pending.get("reminder_minutes", DEFAULT_REMINDER_MINUTES)
    schedule_reminders_for_event(uid, google_event_id, title, start, reminder_minutes)

    # 팀 이벤트 DB 저장 (INSERT + google_event_id 를 단일 트랜잭션으로)
    team_event_id = db.create_team_event_with_google_id(
        title, start, end, uid, priority, google_event_id or ""
    )

    # 공용 캘린더에도 기록 (설정돼 있을 경우)
    label = team_service.PRIORITY_LABEL[priority]
    user_record = db.get_user(uid)
    creator_name = user_record.get("full_name", str(uid)) if user_record else str(uid)
    creator_dept = user_record.get("department", "") if user_record else ""
    dept_str = f" ({creator_dept})" if creator_dept else ""
    try:
        write_to_shared_calendar(
            ADMIN_TELEGRAM_IDS[0],
            title=f"[팀] {title}",
            start=start,
            end=end,
            description=(
                f"👤 등록자: {creator_name}{dept_str}\n"
                f"중요도: {label}"
            ),
        )
    except Exception:
        logger.debug("공용 캘린더 기록 생략 (미설정 또는 관리자 미연동)")  # 정상적 상황, DEBUG 레벨

    # ── 참석 초대 발송 ───────────────────────────────────────────────────────
    await _send_attendance_invites(ctx.bot, team_event_id, pending, uid,
                                   creator_name, title, start)

    if not other_conflicts:
        await ctx.bot.send_message(
            chat_id=uid,
            text=(
                f"✅ *{title}* 등록 완료!\n"
                f"중요도: {label}\n"
                f"팀 캘린더 충돌 없음 👍"
            ),
            parse_mode="Markdown",
        )
        return

    # 타인 충돌 처리 (본인 충돌은 이미 위에서 경고 처리됨)
    result = await team_service.handle_conflicts(
        bot=ctx.bot,
        team_event_id=team_event_id,
        new_priority=priority,
        conflicts=other_conflicts,
        admin_ids=ADMIN_TELEGRAM_IDS,
    )

    if result["blocked"]:
        await ctx.bot.send_message(
            chat_id=uid,
            text=(
                f"🚫 *{title}* 등록은 됐지만 충돌 주의!\n"
                f"해당 시간에 {team_service.PRIORITY_LABEL['red']} 일정이 있는 팀원이 있습니다.\n"
                f"일정 변경을 권장합니다."
            ),
            parse_mode="Markdown",
        )
    elif result["escalated"]:
        await ctx.bot.send_message(
            chat_id=uid,
            text=(
                f"⚠️ *{title}* 등록됐습니다.\n"
                f"🔴 vs 🔴 충돌 발생 — 관리자에게 조율 요청을 보냈습니다."
            ),
            parse_mode="Markdown",
        )
    elif result["notified"]:
        names = ", ".join(result["notified"])
        await ctx.bot.send_message(
            chat_id=uid,
            text=(
                f"✅ *{title}* 등록됐습니다.\n"
                f"충돌 팀원 ({names}) 에게 조율 요청을 보냈습니다."
            ),
            parse_mode="Markdown",
        )


async def _send_attendance_invites(bot, team_event_id: int, pending: dict,
                                   organizer_uid: int, creator_name: str,
                                   title: str, start_iso: str) -> None:
    """초대된 팀원에게 참석 여부 요청 메시지 발송."""
    invited_uids = pending.get("invited_uids", [])
    if not invited_uids:
        return
    try:
        start_dt = datetime.fromisoformat(start_iso).astimezone(_tz).strftime('%m월 %d일 %H:%M')
    except Exception:
        start_dt = start_iso[:16]

    for invited_uid in invited_uids:
        if invited_uid == organizer_uid:
            continue
        db.add_attendee(team_event_id, invited_uid)
        try:
            await bot.send_message(
                chat_id=invited_uid,
                text=(
                    f"📋 *팀 일정 초대*\n\n"
                    f"📌 {title}\n"
                    f"📅 {start_dt}\n"
                    f"👤 등록자: {creator_name}\n\n"
                    f"참석 여부를 알려주세요."
                ),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ 참석", callback_data=f"attend_yes:{team_event_id}"),
                    InlineKeyboardButton("❌ 불참", callback_data=f"attend_no:{team_event_id}"),
                ]]),
            )
        except Exception:
            logger.warning("참석 초대 전송 실패 uid=%s", invited_uid, exc_info=True)


async def attendance_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """참석(attend_yes) / 불참(attend_no) 응답 처리."""
    query = update.callback_query
    await query.answer()
    action, event_id_str = query.data.split(":")
    team_event_id = int(event_id_str)
    uid = query.from_user.id

    event = db.get_team_event(team_event_id)
    if not event:
        await query.edit_message_text("⚠️ 일정을 찾을 수 없습니다.")
        return

    attendees    = db.get_attendees(team_event_id)
    my_record    = next((a for a in attendees if a['user_id'] == uid), None)
    if not my_record:
        await query.edit_message_text("⚠️ 초대 내역을 찾을 수 없습니다.")
        return
    if my_record['status'] != 'pending':
        await query.edit_message_text("이미 응답한 초대입니다.")
        return

    organizer_id = event['organizer_id']
    title        = event['title']
    user_record  = db.get_user(uid)
    user_name    = (user_record.get('full_name') or str(uid)) if user_record else str(uid)

    if action == "attend_yes":
        db.update_attendee_status(team_event_id, uid, 'accepted')
        await query.edit_message_text(
            f"✅ *{title}* 참석으로 응답했습니다.", parse_mode="Markdown"
        )
        notify_text = f"✅ *{user_name}* 님이 *{title}* 참석을 수락했습니다."
    else:
        db.update_attendee_status(team_event_id, uid, 'declined')
        await query.edit_message_text(
            f"❌ *{title}* 불참으로 응답했습니다.", parse_mode="Markdown"
        )
        notify_text = f"❌ *{user_name}* 님이 *{title}* 참석을 거절했습니다."

    try:
        await ctx.bot.send_message(chat_id=organizer_id, text=notify_text,
                                   parse_mode="Markdown")
    except Exception:
        logger.warning("참석 응답 알림 전송 실패 organizer=%s", organizer_id, exc_info=True)


async def conflict_response_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """충돌 상대방의 수락/거절 처리."""
    query    = update.callback_query
    await query.answer()
    action, conflict_id_str = query.data.split(":")
    conflict_id = int(conflict_id_str)
    uid = query.from_user.id

    # 내 pending conflict 조회
    pending = next(
        (c for c in db.get_pending_conflicts_for_user(uid) if c["id"] == conflict_id),
        None,
    )
    if not pending:
        await query.edit_message_text("이미 처리된 요청입니다.")
        return

    organizer_id = pending["organizer_id"]
    title        = pending["title"]

    if action == "conflict_accept":
        db.resolve_conflict(conflict_id, "accepted")
        await query.edit_message_text(
            f"✅ 조율 가능으로 응답했습니다. 주최자에게 알립니다.")
        try:
            await ctx.bot.send_message(
                chat_id=organizer_id,
                text=(
                    f"✅ *{query.from_user.full_name}* 님이 *{title}* 일정 충돌에 대해\n"
                    f"*조율 가능*하다고 응답했습니다."
                ),
                parse_mode="Markdown",
            )
        except Exception:
            logger.warning("충돌 수락 알림 전송 실패 organizer=%s", organizer_id, exc_info=True)

    elif action == "conflict_decline":
        db.resolve_conflict(conflict_id, "declined")
        await query.edit_message_text(
            f"❌ 변경 불가로 응답했습니다. 주최자에게 알립니다.")
        try:
            await ctx.bot.send_message(
                chat_id=organizer_id,
                text=(
                    f"❌ *{query.from_user.full_name}* 님이 *{title}* 일정 충돌에 대해\n"
                    f"*변경 불가*라고 응답했습니다. 일정 재조율을 고려해 주세요."
                ),
                parse_mode="Markdown",
            )
        except Exception:
            logger.warning("충돌 거절 알림 전송 실패 organizer=%s", organizer_id, exc_info=True)


def team_callbacks():
    return [
        CallbackQueryHandler(priority_callback,          pattern=r"^priority:"),
        CallbackQueryHandler(attendance_callback,        pattern=r"^attend_(yes|no):"),
        CallbackQueryHandler(conflict_response_callback, pattern=r"^conflict_(accept|decline):"),
    ]
