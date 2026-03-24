"""
이용권한 신청/승인 플로우 핸들러
- /start      : 최초 진입, 미등록 사용자 안내
- /register   : 이름·소속·목적 입력 흐름
- /status     : 내 권한 상태 확인
- /connect    : Google Calendar 연동
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler,
    MessageHandler, filters, CallbackQueryHandler,
)

import db as db
from config import ADMIN_TELEGRAM_IDS
from models.user import UserStatus
from services.calendar_service import get_auth_url, exchange_code
from handlers.calendar_handler import get_main_menu

# 대화 상태
DEPT, PURPOSE = range(2)
GOOGLE_CODE = 10


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.upsert_user(user.id, user.username or "", user.full_name or "")
    record = db.get_user(user.id)

    status = record.get("status") if record else None

    if status == UserStatus.APPROVED:
        await update.message.reply_text(
            f"👋 안녕하세요, {user.first_name}님!\n"
            "스케줄 챗봇에 오신 걸 환영해요.\n\n"
            "하단 메뉴 버튼을 누르거나 자연어로 일정을 말씀해 주세요. 😊\n"
            "예: *내일 오후 3시에 팀 미팅 잡아줘*",
            parse_mode="Markdown",
            reply_markup=get_main_menu(),
        )
    elif status == UserStatus.PENDING:
        await update.message.reply_text(
            "⏳ 이용 신청이 접수되어 있습니다.\n"
            "관리자 승인 후 사용 가능합니다. 잠시만 기다려 주세요."
        )
    elif status == UserStatus.REJECTED:
        reason = record.get("rejected_reason", "")
        await update.message.reply_text(
            f"❌ 이용 신청이 거부되었습니다.\n사유: {reason or '(사유 없음)'}\n\n"
            "다시 신청하려면 /register 를 입력해 주세요."
        )
    elif status == UserStatus.SUSPENDED:
        await update.message.reply_text("🚫 계정이 정지된 상태입니다. 관리자에게 문의하세요.")
    else:
        await update.message.reply_text(
            "👋 안녕하세요! 스케줄 관리 챗봇입니다.\n\n"
            "이 봇은 *승인된 사용자만* 이용 가능합니다.\n"
            "/register 명령어로 이용 신청을 해주세요.",
            parse_mode="Markdown",
        )


async def cmd_register_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("소속 부서를 입력해 주세요.\n예: 투자심사팀")
    return DEPT


async def reg_dept(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["dept"] = update.message.text.strip()
    await update.message.reply_text("사용 목적을 간단히 입력해 주세요.\n예: 팀 일정 자동 관리")
    return PURPOSE


async def reg_purpose(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    dept = ctx.user_data.get("dept", "")
    purpose = update.message.text.strip()

    db.update_user_registration(user.id, dept, purpose)

    await update.message.reply_text(
        "✅ 이용 신청이 완료되었습니다!\n"
        f"👤 이름: {user.full_name}\n"
        f"🏢 소속: {dept}\n"
        f"📝 목적: {purpose}\n\n"
        "관리자 승인 후 알림을 보내드릴게요. 잠시만 기다려 주세요."
    )

    # 관리자에게 알림
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ 승인", callback_data=f"approve:{user.id}"),
            InlineKeyboardButton("❌ 거부", callback_data=f"reject:{user.id}"),
        ]
    ])
    msg = (
        f"📋 *새 이용 신청*\n\n"
        f"👤 이름: {user.full_name}\n"
        f"🆔 ID: `{user.id}`\n"
        f"🏢 소속: {dept}\n"
        f"📝 목적: {purpose}"
    )
    for admin_id in ADMIN_TELEGRAM_IDS:
        try:
            await ctx.bot.send_message(
                chat_id=admin_id, text=msg,
                parse_mode="Markdown", reply_markup=keyboard,
            )
        except Exception:
            pass

    return ConversationHandler.END


async def reg_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("신청이 취소되었습니다.")
    return ConversationHandler.END


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    record = db.get_user(update.effective_user.id)
    if not record:
        await update.message.reply_text("신청 내역이 없습니다. /register 로 신청하세요.")
        return

    status_emoji = {
        UserStatus.PENDING:   "⏳ 승인 대기 중",
        UserStatus.APPROVED:  "✅ 승인됨",
        UserStatus.REJECTED:  "❌ 거부됨",
        UserStatus.SUSPENDED: "🚫 정지됨",
        UserStatus.EXPIRED:   "⌛ 만료됨",
    }
    label = status_emoji.get(record["status"], record["status"])
    text = f"*내 계정 상태*\n상태: {label}\n소속: {record.get('department','')}\n신청일: {record.get('created_at','')[:10]}"
    if record.get("approved_at"):
        text += f"\n승인일: {record['approved_at'][:10]}"
    if record.get("expires_at"):
        text += f"\n만료일: {record['expires_at'][:10]}"
    await update.message.reply_text(text, parse_mode="Markdown")


# ── Google 연동 ───────────────────────────────────────────

async def cmd_connect(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    record = db.get_user(user.id)
    if not record or record["status"] != UserStatus.APPROVED:
        await update.message.reply_text("승인된 사용자만 Google Calendar를 연동할 수 있습니다.")
        return ConversationHandler.END

    url = get_auth_url(user.id)
    await update.message.reply_text(
        "🔗 *Google Calendar 연동*\n\n"
        "아래 링크에서 Google 계정을 인증한 뒤,\n"
        "받은 코드를 이 채팅에 붙여넣어 주세요.\n\n"
        f"[인증 링크 열기]({url})",
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )
    return GOOGLE_CODE


async def google_code_received(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    success = exchange_code(update.effective_user.id, code)
    if success:
        await update.message.reply_text(
            "✅ Google Calendar 연동이 완료되었습니다!\n"
            "이제 자연어로 일정을 관리해 보세요. 😊"
        )
    else:
        await update.message.reply_text(
            "❌ 코드가 올바르지 않습니다. 다시 /connect 를 입력해 주세요."
        )
    return ConversationHandler.END


# ── ConversationHandler 팩토리 ────────────────────────────

def registration_conv() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("register", cmd_register_start)],
        states={
            DEPT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_dept)],
            PURPOSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_purpose)],
        },
        fallbacks=[CommandHandler("cancel", reg_cancel)],
    )


def connect_conv() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("connect", cmd_connect)],
        states={
            GOOGLE_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, google_code_received)],
        },
        fallbacks=[CommandHandler("cancel", reg_cancel)],
    )
