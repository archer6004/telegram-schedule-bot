"""
관리자 전용 핸들러
- /admin      : 대시보드
- /setup_team : 팀 공용 캘린더 생성
- Callback    : approve / reject / suspend / delete / user_list / user_detail
"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler

logger = logging.getLogger(__name__)

import db as db
from config import ADMIN_TELEGRAM_IDS, OWNER_TELEGRAM_IDS
from constants import STATUS_ICON
from models.user import UserStatus
from utils import escape_md

ROLE_ICON = {"OWNER": "👑", "ADMIN": "🛡", "MEMBER": "👤"}


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_TELEGRAM_IDS


def _is_owner(user_id: int) -> bool:
    return user_id in OWNER_TELEGRAM_IDS


def _user_name(user_record: dict | None, fallback: int) -> str:
    return user_record.get("full_name", str(fallback)) if user_record else str(fallback)


# ── /setup_team ───────────────────────────────────────────

async def cmd_setup_team(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """팀 공용 캘린더를 관리자 Google 계정에 생성합니다."""
    uid = update.effective_user.id
    if not _is_admin(uid):
        await update.message.reply_text("❌ 관리자 전용 명령어입니다.")
        return

    existing = db.get_setting("shared_calendar_id")
    if existing:
        await update.message.reply_text(
            f"ℹ️ 이미 팀 공용 캘린더가 설정되어 있습니다.\n`{existing}`",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text("⏳ 팀 공용 캘린더 생성 중...")
    try:
        from services.calendar_service import create_shared_calendar
        calendar_id = create_shared_calendar(uid)
        await update.message.reply_text(
            f"✅ 팀 공용 캘린더가 생성됐습니다!\n`{calendar_id}`",
            parse_mode="Markdown",
        )
    except PermissionError:
        await update.message.reply_text(
            "❌ 관리자 Google 계정이 연동되지 않았습니다. 먼저 /connect 로 연동해 주세요."
        )
    except Exception as e:
        await update.message.reply_text(f"❌ 생성 실패: {e}")


# ── /admin 대시보드 ───────────────────────────────────────

async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("❌ 관리자 전용 명령어입니다.")
        return

    uid = update.effective_user.id
    stats = db.get_stats()
    text = (
        "👑 *관리자 대시보드*\n\n"
        f"⏳ 승인 대기: *{stats['pending']}명*\n"
        f"✅ 활성 사용자: *{stats['approved']}명*\n"
        f"📊 오늘 요청: *{stats['today_actions']}건*"
    )
    rows = [[
        InlineKeyboardButton("📋 신청 목록",   callback_data="admin:pending_list"),
        InlineKeyboardButton("👥 전체 사용자", callback_data="admin:user_list"),
    ]]
    # OWNER 전용 행 추가
    if _is_owner(uid):
        rows.append([
            InlineKeyboardButton("👑 역할 관리",   callback_data="owner:role_list"),
            InlineKeyboardButton("⚙️ 시스템 설정", callback_data="owner:system"),
        ])
    await update.message.reply_text(
        text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(rows),
    )


# ── 콜백 서브핸들러 ───────────────────────────────────────

async def _handle_pending_list(query):
    users = db.get_users_by_status(UserStatus.PENDING)
    if not users:
        await query.edit_message_text("⏳ 대기 중인 신청이 없습니다.")
        return

    lines = ["📋 *승인 대기 목록*\n"]
    for u in users[:10]:
        lines.append(f"👤 {u['full_name']} ({u.get('department','')}) — ID `{u['telegram_id']}`")

    buttons = [
        [
            InlineKeyboardButton(f"✅ {u['full_name']} 승인", callback_data=f"approve:{u['telegram_id']}"),
            InlineKeyboardButton("❌ 거부", callback_data=f"reject:{u['telegram_id']}"),
        ]
        for u in users[:5]
    ]
    await query.edit_message_text(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def _handle_user_list(query):
    all_users = db.get_all_users()
    if not all_users:
        await query.edit_message_text("등록된 사용자가 없습니다.")
        return

    lines = [f"👥 *전체 사용자 ({len(all_users)}명)*\n"]
    buttons = []
    for u in all_users[:20]:
        icon = STATUS_ICON.get(u.get("status", ""), "❓")
        gcal = "📅" if u.get("google_token") else "  "
        name = escape_md(u.get("full_name") or "?")
        dept = escape_md(u.get("department") or "")
        lines.append(f"{icon}{gcal} {name}  {dept}")
        buttons.append([InlineKeyboardButton(
            f"{icon} {u.get('full_name', '?')}",
            callback_data=f"admin:user_detail:{u['telegram_id']}",
        )])

    lines.append("\n✅승인  ⏳대기  ❌거부  🚫정지  📅캘린더연동")
    await query.edit_message_text(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def _handle_user_detail(query, target_id: int):
    u = db.get_user(target_id)
    if not u:
        await query.edit_message_text("사용자를 찾을 수 없습니다.")
        return

    viewer_id = query.from_user.id
    role = u.get("role") or "MEMBER"
    role_label = ROLE_ICON.get(role, "👤") + " " + role
    icon = STATUS_ICON.get(u.get("status", ""), "❓")
    gcal = (f"📅 {escape_md(u['google_email'])}" if u.get("google_email")
            else ("📅 연동됨" if u.get("google_token") else "미연동"))
    lines = [
        f"👤 *{escape_md(u.get('full_name', '?'))}*",
        f"역할: {role_label}",
        f"상태: {icon} {u.get('status', '')}",
        f"부서: {escape_md(u.get('department') or '-')}",
        f"목적: {escape_md(u.get('purpose') or '-')}",
        f"Google: {gcal}",
        f"가입: {(u.get('created_at') or '')[:10]}",
    ]
    if u.get("approved_at"):
        lines.append(f"승인: {u['approved_at'][:10]}")
    if u.get("rejected_reason"):
        lines.append(f"거부사유: {u['rejected_reason']}")

    action_buttons = []
    status = u.get("status", "")
    if status == "APPROVED":
        action_buttons.append(InlineKeyboardButton("🚫 정지", callback_data=f"admin:suspend:{target_id}"))
    elif status in ("SUSPENDED", "REJECTED"):
        action_buttons.append(InlineKeyboardButton("✅ 재승인", callback_data=f"approve:{target_id}"))
    elif status == "PENDING":
        action_buttons += [
            InlineKeyboardButton("✅ 승인", callback_data=f"approve:{target_id}"),
            InlineKeyboardButton("❌ 거부", callback_data=f"reject:{target_id}"),
        ]

    rows = []
    if action_buttons:
        rows.append(action_buttons)

    # OWNER 전용: 역할 관리 버튼 (본인 제외)
    if _is_owner(viewer_id) and target_id != viewer_id:
        if role == "MEMBER":
            rows.append([InlineKeyboardButton(
                "🛡 ADMIN으로 임명", callback_data=f"admin:role_set:{target_id}:ADMIN"
            )])
        elif role == "ADMIN":
            rows.append([InlineKeyboardButton(
                "👤 MEMBER로 변경", callback_data=f"admin:role_set:{target_id}:MEMBER"
            )])

    rows.append([InlineKeyboardButton("🗑 탈퇴 처리", callback_data=f"admin:delete_confirm:{target_id}")])
    rows.append([InlineKeyboardButton("◀ 목록으로", callback_data="admin:user_list")])

    await query.edit_message_text(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def _handle_delete_confirm(query, target_id: int):
    u = db.get_user(target_id)
    name = _user_name(u, target_id)
    await query.edit_message_text(
        f"⚠️ *정말로 {name} 님을 탈퇴 처리하시겠습니까?*\n\n"
        "DB에서 완전히 삭제되며 복구할 수 없습니다.\n"
        "Google 연동 정보도 함께 삭제됩니다.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ 탈퇴 확인", callback_data=f"admin:delete_do:{target_id}"),
            InlineKeyboardButton("◀ 취소", callback_data=f"admin:user_detail:{target_id}"),
        ]]),
    )


async def _handle_delete_do(query, ctx, target_id: int):
    u = db.get_user(target_id)
    name = _user_name(u, target_id)
    db.delete_user(target_id)
    await query.edit_message_text(
        f"🗑 *{name}* 님이 탈퇴 처리됐습니다.", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("◀ 목록으로", callback_data="admin:user_list")
        ]]),
    )
    try:
        await ctx.bot.send_message(chat_id=target_id, text="📢 계정이 탈퇴 처리되었습니다. 이용해 주셔서 감사합니다.")
    except Exception:
        logger.warning("탈퇴 알림 전송 실패 uid=%s", target_id, exc_info=True)


async def _handle_suspend(query, ctx, target_id: int) -> None:
    db.suspend_user(target_id)
    name = _user_name(db.get_user(target_id), target_id)
    await query.edit_message_text(f"🚫 {name} 님을 정지했습니다.")
    try:
        await ctx.bot.send_message(chat_id=target_id, text="🚫 계정이 정지되었습니다. 문의사항은 관리자에게 연락하세요.")
    except Exception:
        logger.warning("정지 알림 전송 실패 uid=%s", target_id, exc_info=True)


async def _handle_approve(query, ctx, target_id: int) -> None:
    db.approve_user(target_id)
    name = _user_name(db.get_user(target_id), target_id)
    await query.edit_message_text(f"✅ {name} 님을 승인했습니다.")
    try:
        already_connected = bool(db.get_google_token(target_id))
        if already_connected:
            # 이미 연동된 사용자 (재승인 등) → 연동 버튼 없이 간단 알림
            await ctx.bot.send_message(
                chat_id=target_id,
                text=(
                    "🎉 *이용 신청이 승인되었습니다!*\n\n"
                    "하단 메뉴를 통해 일정 관리를 시작해 보세요. 😊"
                ),
                parse_mode="Markdown",
            )
        else:
            # 미연동 사용자 → Google 연동 버튼 제공
            from services.calendar_service import get_auth_url
            url = get_auth_url(target_id)
            await ctx.bot.send_message(
                chat_id=target_id,
                text=(
                    "🎉 *이용 신청이 승인되었습니다!*\n\n"
                    "아래 버튼을 탭해서 Google Calendar를 연동하면\n"
                    "바로 일정 관리를 시작할 수 있습니다."
                ),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📅 Google Calendar 연동하기", url=url)
                ]]),
            )
    except Exception:
        logger.warning("승인 알림 전송 실패 uid=%s", target_id, exc_info=True)


async def _handle_role_list(query) -> None:
    """OWNER 전용: 전체 사용자 역할 목록 + 빠른 역할 변경."""
    if not _is_owner(query.from_user.id):
        await query.edit_message_text("❌ OWNER 권한이 필요합니다.")
        return
    users = db.get_all_users()
    lines = ["👑 *역할 관리*\n"]
    buttons = []
    for u in users[:20]:
        role  = u.get("role") or "MEMBER"
        icon  = ROLE_ICON.get(role, "👤")
        name  = u.get("full_name") or "?"
        lines.append(f"{icon} {escape_md(name)}  ({role})")
        # 본인(OWNER) 제외, MEMBER↔ADMIN 전환 버튼
        if u["telegram_id"] != query.from_user.id:
            if role == "MEMBER":
                label = f"🛡 {name} → ADMIN"
                cb    = f"admin:role_set:{u['telegram_id']}:ADMIN"
            elif role == "ADMIN":
                label = f"👤 {name} → MEMBER"
                cb    = f"admin:role_set:{u['telegram_id']}:MEMBER"
            else:
                continue
            buttons.append([InlineKeyboardButton(label, callback_data=cb)])
    lines.append("\n👑OWNER  🛡ADMIN  👤MEMBER")
    buttons.append([InlineKeyboardButton("◀ 대시보드로", callback_data="owner:back_dashboard")])
    await query.edit_message_text(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def _handle_system_settings(query) -> None:
    """OWNER 전용: 시스템 설정 현황."""
    if not _is_owner(query.from_user.id):
        await query.edit_message_text("❌ OWNER 권한이 필요합니다.")
        return
    cal_id    = db.get_setting("shared_calendar_id") or "미설정"
    owner_uid = db.get_setting("shared_calendar_owner_uid") or "미설정"
    cal_short = cal_id[:30] + "..." if len(cal_id) > 30 else cal_id
    lines = [
        "⚙️ *시스템 설정*\n",
        f"📅 팀 공용 캘린더: `{escape_md(cal_short)}`",
        f"🔑 캘린더 소유자 UID: `{owner_uid}`",
    ]
    rows = [[InlineKeyboardButton("◀ 대시보드로", callback_data="owner:back_dashboard")]]
    if cal_id == "미설정":
        rows.insert(0, [InlineKeyboardButton("📅 팀 캘린더 생성 → /setup_team", callback_data="owner:noop")])
    await query.edit_message_text(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def _handle_role_set(query, viewer_id: int, target_id: int, new_role: str) -> None:
    """OWNER 전용: 사용자 역할 변경."""
    if not _is_owner(viewer_id):
        await query.edit_message_text("❌ OWNER 권한이 필요합니다.")
        return
    u = db.get_user(target_id)
    if not u:
        await query.edit_message_text("사용자를 찾을 수 없습니다.")
        return
    db.set_user_role(target_id, new_role)
    name = _user_name(u, target_id)
    role_label = ROLE_ICON.get(new_role, "👤") + " " + new_role
    await query.edit_message_text(
        f"✅ *{escape_md(name)}* 님의 역할이 {role_label} 으로 변경됐습니다.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("◀ 상세보기", callback_data=f"admin:user_detail:{target_id}"),
        ]]),
    )
    try:
        role_msg = {"ADMIN": "🛡 관리자(ADMIN) 권한이 부여되었습니다.", "MEMBER": "👤 일반 사용자(MEMBER)로 변경되었습니다."}.get(new_role, "")
        if role_msg:
            await query.bot.send_message(chat_id=target_id, text=role_msg)
    except Exception:
        logger.warning("역할 변경 알림 실패 uid=%s", target_id, exc_info=True)


async def _handle_reject(query, ctx, target_id: int) -> None:
    db.reject_user(target_id, reason="관리자 판단에 의해 거부됨")
    name = _user_name(db.get_user(target_id), target_id)
    await query.edit_message_text(f"❌ {name} 님의 신청을 거부했습니다.")
    try:
        await ctx.bot.send_message(
            chat_id=target_id,
            text="❌ 이용 신청이 거부되었습니다.\n문의사항이 있으면 관리자에게 연락하세요.",
        )
    except Exception:
        logger.warning("거부 알림 전송 실패 uid=%s", target_id, exc_info=True)


# ── 메인 콜백 디스패처 ────────────────────────────────────

async def admin_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not _is_admin(query.from_user.id):
        await query.edit_message_text("❌ 권한이 없습니다.")
        return

    data = query.data

    if data == "admin:pending_list":
        await _handle_pending_list(query)
    elif data == "admin:user_list":
        await _handle_user_list(query)
    elif data.startswith("admin:user_detail:"):
        await _handle_user_detail(query, int(data.split(":")[2]))
    elif data.startswith("admin:delete_confirm:"):
        await _handle_delete_confirm(query, int(data.split(":")[2]))
    elif data.startswith("admin:delete_do:"):
        await _handle_delete_do(query, ctx, int(data.split(":")[2]))
    elif data.startswith("admin:suspend:"):
        await _handle_suspend(query, ctx, int(data.split(":")[2]))
    elif data.startswith("admin:role_set:"):
        parts = data.split(":")
        await _handle_role_set(query, query.from_user.id, int(parts[2]), parts[3])
    elif data == "owner:role_list":
        await _handle_role_list(query)
    elif data == "owner:system":
        await _handle_system_settings(query)
    elif data == "owner:back_dashboard":
        # 대시보드 텍스트 재출력
        stats = db.get_stats()
        text = (
            "👑 *관리자 대시보드*\n\n"
            f"⏳ 승인 대기: *{stats['pending']}명*\n"
            f"✅ 활성 사용자: *{stats['approved']}명*\n"
            f"📊 오늘 요청: *{stats['today_actions']}건*"
        )
        rows = [[
            InlineKeyboardButton("📋 신청 목록",   callback_data="admin:pending_list"),
            InlineKeyboardButton("👥 전체 사용자", callback_data="admin:user_list"),
        ], [
            InlineKeyboardButton("👑 역할 관리",   callback_data="owner:role_list"),
            InlineKeyboardButton("⚙️ 시스템 설정", callback_data="owner:system"),
        ]]
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))
    elif data == "owner:noop":
        await query.answer("텔레그램 채팅창에 /setup_team 입력", show_alert=True)
    elif data.startswith("approve:"):
        await _handle_approve(query, ctx, int(data.split(":")[1]))
    elif data.startswith("reject:"):
        await _handle_reject(query, ctx, int(data.split(":")[1]))
