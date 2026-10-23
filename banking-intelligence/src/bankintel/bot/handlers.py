from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from sqlalchemy.ext.asyncio import async_sessionmaker

import asyncio

from bankintel.bot import views
from bankintel.collector import collect_all
from bankintel.config import get_settings
from bankintel.sources.fetcher import build_fetcher

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(views.start_text())


@router.message(Command("banks"))
async def cmd_banks(message: Message, session_factory: async_sessionmaker) -> None:
    async with session_factory() as session:
        await message.answer(await views.banks_text(session))


@router.message(Command("status"))
async def cmd_status(message: Message, session_factory: async_sessionmaker) -> None:
    async with session_factory() as session:
        await message.answer(await views.status_text(session))


_refresh_lock = asyncio.Lock()


@router.message(Command("refresh"))
async def cmd_refresh(message: Message, session_factory: async_sessionmaker) -> None:
    if _refresh_lock.locked():
        await message.answer("Обновление уже идёт, дождитесь окончания.")
        return
    async with _refresh_lock:
        settings = get_settings()
        await message.answer("Запускаю сбор по подтверждённым источникам…")
        fetcher = build_fetcher(settings)
        try:
            async with session_factory() as session:
                results = await collect_all(session, fetcher, settings.raw_storage_dir)
        finally:
            await fetcher.aclose()
        await message.answer(views.refresh_text(results))


def _planned_handler(command: str):
    async def handler(message: Message) -> None:
        await message.answer(views.planned_text(command))

    handler.__name__ = f"cmd_{command}"
    return handler


for _cmd in views.PLANNED:
    router.message.register(_planned_handler(_cmd), Command(_cmd))
