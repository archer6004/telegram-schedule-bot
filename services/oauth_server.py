"""
임시 OAuth 콜백 서버 — /connect 인증 코드를 자동 수신
aiohttp 를 기존 asyncio 이벤트 루프 안에서 실행합니다.
Desktop 타입 credentials.json 은 127.0.0.1 loopback 을 자동 허용합니다.
"""
import asyncio
import logging
from aiohttp import web

logger = logging.getLogger(__name__)

PORT = 8088
CALLBACK_PATH = "/oauth/callback"
REDIRECT_URI = f"http://127.0.0.1:{PORT}{CALLBACK_PATH}"


async def wait_for_oauth(telegram_id: int, bot, timeout: int = 300) -> None:
    """OAuth 콜백 서버를 시작하고 코드 수신 → 토큰 교환 → 결과 메시지 전송."""
    from services.calendar_service import exchange_code

    queue: asyncio.Queue = asyncio.Queue()

    async def _handler(request: web.Request) -> web.Response:
        code = request.rel_url.query.get("code")
        error = request.rel_url.query.get("error")
        await queue.put(("code", code) if code else ("error", error or "unknown"))

        if code:
            html = (
                "<html><body style='font-family:sans-serif;text-align:center;padding:60px'>"
                "<h2>✅ 인증 완료!</h2><p>텔레그램으로 돌아가세요.</p>"
                "<script>setTimeout(()=>window.close(),2000)</script>"
                "</body></html>"
            )
        else:
            html = (
                f"<html><body style='font-family:sans-serif;text-align:center;padding:60px'>"
                f"<h2>❌ 인증 실패</h2><p>{error}</p>"
                f"</body></html>"
            )
        return web.Response(text=html, content_type="text/html")

    app = web.Application()
    app.router.add_get(CALLBACK_PATH, _handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", PORT)

    try:
        await site.start()
        logger.info("OAuth 서버 시작 — port %d", PORT)
    except OSError:
        await bot.send_message(
            chat_id=telegram_id,
            text="⚠️ OAuth 서버 포트(8088)가 이미 사용 중입니다. 잠시 후 /connect 를 다시 시도해주세요.",
        )
        await runner.cleanup()
        return

    try:
        kind, value = await asyncio.wait_for(queue.get(), timeout=timeout)
    except asyncio.TimeoutError:
        await bot.send_message(
            chat_id=telegram_id,
            text="⏰ 인증 시간 초과 (5분). /connect 를 다시 시도해주세요.",
        )
        return
    finally:
        await runner.cleanup()
        logger.info("OAuth 서버 종료")

    if kind == "code":
        success = exchange_code(telegram_id, value)
        if success:
            await bot.send_message(
                chat_id=telegram_id,
                text="✅ Google Calendar 연동 완료!\n이제 자연어로 일정을 관리해 보세요. 😊",
            )
        else:
            await bot.send_message(
                chat_id=telegram_id,
                text="❌ 코드 교환 실패. /connect 를 다시 시도해주세요.",
            )
    else:
        await bot.send_message(
            chat_id=telegram_id,
            text=f"❌ Google 인증 취소됨: {value}",
        )
