"""
관리자 전용 핸들러
- /admin   : 대시보드
- Callback : approve / reject 버튼 처리
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler

import db as db
from config import ADMIN_TELEGRAM_IDS
from models.user import UserStatus


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_TELEGRAM_IDS


async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("❌ 관리자 전용 명령어입니다.")
        return

    stats = db.get_stats()
    pending_users = db.get_users_by_status(UserStatus.PENDING)

    text = (
        "👑 *관리자 대시보드*\n\n"
        f"⏳ 승인 대기: *{stats['pending']}명*\n"
        f"✅ 활성 사용자: *{stats['approved']}명*\n"
        f"📊 오늘 요청: *{stats['today_actions']}건*"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 신청 목록", callback_data="admin:pending_list"),
            InlineKeyboardButton("👥 전체 사용자", callback_data="admin:user_list"),
        ]
    ])

    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def admin_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not _is_admin(query.from_user.id):
        await query.edit_message_text("❌ 권한이 없습니다.")
        return

    data = query.data

    # ── 신청 목록 ───────────────────────────────────────
    if data == "admin:pending_list":
        users = db.get_users_by_status(UserStatus.PENDING)
        if not users:
            await query.edit_message_text("⏳ 대기 중인 신청이 없습니다.")
            return

        lines = ["📋 *승인 대기 목록*\n"]
        for u in users[:10]:
            lines.append(
                f"👤 {u['full_name']} ({u.get('department','')}) — ID `{u['telegram_id']}`"
            )
        buttons = [
            [
                InlineKeyboardButton(f"✅ {u['full_name']} 승인",
                                     callback_data=f"approve:{u['telegram_id']}"),
                InlineKeyboardButton("❌ 거부",
                                     callback_data=f"reject:{u['telegram_id']}"),
            ]
            for u in users[:5]
        ]
        await query.edit_message_text(
            "\n".join(lines), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    # ── 전체 사용자 목록 ─────────────────────────────────
    elif data == "admin:user_list":
        approved = db.get_users_by_status(UserStatus.APPROVED)
        lines = [f"👥 *활성 사용자 ({len(approved)}명)*\n"]
        for u in approved[:15]:
            lines.append(f"• {u['full_name']} — {u.get('department','')}")
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown")

    # ── 승인 ─────────────────────────────────────────────
    elif data.startswith("approve:"):
        target_id = int(data.split(":")[1])
        db.approve_user(target_id)
        user_record = db.get_user(target_id)
        name = user_record.get("full_name", str(target_id)) if user_record else str(target_id)

        await query.edit_message_text(f"✅ {name} 님을 승인했습니다.")

        # 신청자에게 알림
        try:
            await ctx.bot.send_message(
                chat_id=target_id,
                text=(
                    "🎉 *이용 신청이 승인되었습니다!*\n\n"
                    "이제 Google Calendar를 연동하고 일정 관리를 시작해 보세요.\n"
                    "👉 /connect — Google 계정 연동"
                ),
                parse_mode="Markdown",
            )
        except Exception:
            pass

    # ── 거부 ─────────────────────────────────────────────
    elif data.startswith("reject:"):
        target_id = int(data.split(":")[1])
        db.reject_user(target_id, reason="관리자 판단에 의해 거부됨")
        user_record = db.get_user(target_id)
        name = user_record.get("full_name", str(target_id)) if user_record else str(target_id)

        await query.edit_message_text(f"❌ {name} 님의 신청을 거부했습니다.")

        try:
            await ctx.bot.send_message(
                chat_id=target_id,
                text=(
                    "❌ 이용 신청이 거부되었습니다.\n"
                    "문의사항이 있으면 관리자에게 연락하세요."
                ),
            )
        except Exception:
            pass
