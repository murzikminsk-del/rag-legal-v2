import asyncio
import logging
import ssl

import httpx
import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from bot.config import settings
from bot.handlers import routers
from bot.services.backend_client import BackendClient
from bot.web import build_notify_api


class NoVerifySession(AiohttpSession):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        self._connector_init["ssl"] = ssl_ctx


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    bot = Bot(token=settings.bot_token.get_secret_value(), session=NoVerifySession())
    dp = Dispatcher(storage=MemoryStorage())

    http = httpx.AsyncClient(
        base_url=settings.backend_url,
        timeout=httpx.Timeout(connect=3.0, read=60.0, write=10.0, pool=5.0),
        trust_env=False,
    )
    backend = BackendClient(http)
    dp["backend"] = backend

    for router in routers:
        dp.include_router(router)

    await bot.set_my_commands([
        BotCommand(command="start", description="Начать работу"),
        BotCommand(command="ask", description="Задать вопрос по теме"),
        BotCommand(command="clear", description="Очистить историю"),
        BotCommand(command="cancel", description="Отменить сценарий"),
        BotCommand(command="help", description="Справка"),
    ])

    api = build_notify_api(bot, settings.internal_token.get_secret_value())
    config = uvicorn.Config(api, host="0.0.0.0", port=settings.bot_api_port, log_level="info")
    server = uvicorn.Server(config)

    try:
        await asyncio.gather(dp.start_polling(bot), server.serve())
    finally:
        await backend.aclose()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
    