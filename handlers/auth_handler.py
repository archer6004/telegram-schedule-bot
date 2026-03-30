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
import asyncio
from services.calendar_service import get_auth_url, exchange_code
from services.oauth_server import wait_for_oauth
from handlers.calendar_handler import get_main_menu, _clear_session

# 대화 상태
NAME, DEPT, PURPOSE = range(3)
GOOGLE_CODE = 10


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    _clear_session(ctx)  # stale 대화 상태 초기화
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
        # Google Calendar 미연동 사용자에게만 연동 안내 추가 전송
        if not db.get_google_token(user.id):
            url = get_auth_url(user.id)
            await update.message.reply_text(
                "⚠️ *Google Calendar가 아직 연동되지 않았습니다.*\n\n"
                "연동 후 일정 등록·조회 기능을 사용할 수 있습니다.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📅 Google Calendar 연동하기", url=url)
                ]]),
            )
    elif status == UserStatus.PENDING:
        guide_btn = InlineKeyboardMarkup([[
            InlineKeyboardButton("📖 시작 가이드 보기", callback_data="help:guide"),
        ]])
        await update.message.reply_text(
            "⏳ 이용 신청이 접수되어 있습니다.\n"
            "관리자 승인 후 사용 가능합니다. 잠시만 기다려 주세요.\n\n"
            "_미리 사용법을 확인해 두세요 👇_",
            parse_mode="Markdown",
            reply_markup=guide_btn,
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
        register_btn = InlineKeyboardMarkup([[
            InlineKeyboardButton("✏️ 이용 신청하기", callback_data="auth:register"),
            InlineKeyboardButton("📖 사용법 보기",   callback_data="help:guide"),
        ]])
        await update.message.reply_text(
            "👋 안녕하세요! *팀 스케줄 관리 챗봇*입니다.\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "이 봇으로 할 수 있는 것들:\n\n"
            "📅 *개인 일정 관리*\n"
            "• 자연어로 일정 추가·조회·삭제\n"
            "• Google Calendar 자동 연동\n\n"
            "👥 *팀 일정 관리*\n"
            "• 팀 공용 캘린더에 일정 등록\n"
            "• 충돌 자동 감지 및 조율\n\n"
            "🌤 *날씨 + 일정 연동*\n"
            "• 당일/주간 날씨 기반 일정 조언\n\n"
            "🔔 *리마인더*\n"
            "• 일정 N분 전 자동 알림\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "이용하려면 먼저 이용 신청이 필요합니다.\n"
            "*/register* 명령어 또는 아래 버튼을 눌러 시작하세요! 👇",
            parse_mode="Markdown",
            reply_markup=register_btn,
        )


async def cmd_register_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/register 커맨드 또는 '이용 신청하기' 버튼 → 이름 입력 요청."""
    # 콜백 쿼리(인라인 버튼)로 진입한 경우 answer 처리
    if update.callback_query:
        await update.callback_query.answer()
        send = update.callback_query.message.reply_text
    else:
        send = update.message.reply_text

    await send(
        "✏️ *이용 신청을 시작합니다.*\n\n"
        "먼저 실명을 입력해 주세요.\n"
        "예: 홍길동",
        parse_mode="Markdown",
    )
    return NAME


async def reg_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["real_name"] = update.message.text.strip()
    await update.message.reply_text(
        "소속 팀(부서)을 입력해 주세요.\n예: 투자심사팀"
    )
    return DEPT


async def reg_dept(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["dept"] = update.message.text.strip()
    await update.message.reply_text(
        "사용 목적을 간단히 입력해 주세요.\n예: 팀 일정 자동 관리"
    )
    return PURPOSE


async def reg_purpose(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    real_name = ctx.user_data.get("real_name", user.full_name)
    dept    = ctx.user_data.get("dept", "")
    purpose = update.message.text.strip()

    # full_name을 실명으로 업데이트한 뒤 등록 정보 저장
    db.upsert_user(user.id, user.username or "", real_name)
    db.update_user_registration(user.id, dept, purpose)

    guide_btn = InlineKeyboardMarkup([[
        InlineKeyboardButton("📖 시작 가이드 보기", callback_data="help:guide"),
    ]])
    await update.message.reply_text(
        "✅ 이용 신청이 완료되었습니다!\n\n"
        f"👤 이름: {real_name}\n"
        f"🏢 소속: {dept}\n"
        f"📝 목적: {purpose}\n\n"
        "관리자 승인 후 알림을 보내드릴게요. 잠시만 기다려 주세요.\n\n"
        "_미리 사용법을 확인해 두세요 👇_",
        parse_mode="Markdown",
        reply_markup=guide_btn,
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
        f"👤 이름: {real_name}\n"
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

async def _send_connect_link(chat_id: int, user_id: int, bot):
    """인증 링크 전송 + Mac 자동 캡처 서버 시작."""
    url = get_auth_url(user_id)
    await bot.send_message(
        chat_id=chat_id,
        text=(
            "🔗 *Google Calendar 연동*\n\n"
            "💻 *Mac 브라우저에서 열 경우 (자동)*\n"
            "링크 열기 → Google 허용 → 자동 완료 ✨\n\n"
            "📱 *폰에서 열 경우*\n"
            "① 아래 링크 탭\n"
            "② Google 계정 허용\n"
            "③ 페이지에서 *[📨 텔레그램으로 코드 전송]* 탭\n"
            "④ 텔레그램으로 돌아와서 코드 붙여넣기\n\n"
            f"[👉 인증 링크 열기]({url})\n\n"
            "⏰ 5분 내에 완료해 주세요."
        ),
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )
    asyncio.create_task(wait_for_oauth(user_id, bot))


async def reconnect_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "reconnect_yes":
        await query.edit_message_text("🔄 재연동을 시작합니다...")
        await _send_connect_link(query.message.chat_id, query.from_user.id, ctx.bot)
    else:
        await query.edit_message_text("취소되었습니다.")


async def cmd_connect(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    record = db.get_user(user.id)
    if not record or record["status"] != UserStatus.APPROVED:
        await update.message.reply_text("승인된 사용자만 Google Calendar를 연동할 수 있습니다.")
        return ConversationHandler.END

    # 이미 연동된 경우 경고
    if db.get_google_token(user.id):
        email = (record or {}).get("google_email", "")
        email_line = f"📧 연동 계정: `{email}`\n\n" if email else ""
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔄 재연동", callback_data="reconnect_yes"),
            InlineKeyboardButton("❌ 취소",   callback_data="reconnect_no"),
        ]])
        await update.message.reply_text(
            "⚠️ *이미 Google Calendar가 연동되어 있습니다.*\n\n"
            f"{email_line}"
            "재연동하면 기존 연결이 새 계정으로 교체됩니다.\n"
            "계속하시겠습니까?",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        return ConversationHandler.END

    await _send_connect_link(update.message.chat_id, user.id, ctx.bot)
    return GOOGLE_CODE


async def google_code_received(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """폰 수동 입력: 전체 URL 또는 코드만 붙여넣기 모두 지원."""
    import re
    text = update.message.text.strip()

    # URL 전체를 붙여넣은 경우 code= 파라미터 추출
    match = re.search(r'[?&]code=([^&\s]+)', text)
    code = match.group(1) if match else text

    success = exchange_code(update.effective_user.id, code)
    if success:
        await update.message.reply_text(
            "✅ Google Calendar 연동 완료!\n이제 자연어로 일정을 관리해 보세요. 😊"
        )
    else:
        await update.message.reply_text(
            "❌ 코드가 올바르지 않습니다. 다시 /connect 를 입력해 주세요."
        )
    return ConversationHandler.END


# ── ConversationHandler 팩토리 ────────────────────────────

def registration_conv() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("register", cmd_register_start),
            CallbackQueryHandler(cmd_register_start, pattern="^auth:register$"),
        ],
        states={
            NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_name)],
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
        conversation_timeout=300,
    )
