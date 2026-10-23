from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from bankintel.bot import views

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


def _planned_handler(command: str):
    async def handler(message: Message) -> None:
        await message.answer(views.planned_text(command))

    handler.__name__ = f"cmd_{command}"
    return handler


for _cmd in views.PLANNED:
    router.message.register(_planned_handler(_cmd), Command(_cmd))
