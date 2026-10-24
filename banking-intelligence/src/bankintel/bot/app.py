import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bankintel.bot.access import AllowlistMiddleware
from bankintel.bot.handlers import router
from bankintel.config import get_settings
from bankintel.db.session import make_engine, make_session_factory


def build_dispatcher(allowed_ids: list[int], session_factory) -> Dispatcher:
    dp = Dispatcher(session_factory=session_factory)
    dp.message.outer_middleware(AllowlistMiddleware(allowed_ids))
    dp.include_router(router)
    return dp


async def run() -> None:
    settings = get_settings()
    if settings.bot_token is None:
        raise SystemExit("BOT_TOKEN не задан. Получите токен у @BotFather и укажите его в .env")
    if not settings.allowed_telegram_ids:
        logging.warning("ALLOWED_TELEGRAM_IDS пуст — бот будет отказывать всем пользователям")
    engine = make_engine(settings.database_url)
    dp = build_dispatcher(settings.allowed_telegram_ids, make_session_factory(engine))
    bot = Bot(settings.bot_token.get_secret_value(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        await dp.start_polling(bot)
    finally:
        await engine.dispose()


def main() -> None:
    from bankintel.logging_setup import configure_logging

    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    asyncio.run(run())
