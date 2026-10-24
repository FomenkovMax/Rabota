import asyncio
from html import escape

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import FSInputFile, Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from bankintel.bot import compare_views, views
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


@router.message(Command("compare"))
async def cmd_compare(message: Message, command: CommandObject, session_factory: async_sessionmaker) -> None:
    try:
        scenario = compare_views.parse_scenario(command.args)
    except ValueError as exc:
        await message.answer(escape(str(exc)))  # в тексте есть «<сумма>» — иначе Telegram отклонит HTML
        return
    async with session_factory() as session:
        await message.answer(await compare_views.compare_for_bot(session, scenario))


@router.message(Command("deposits"))
async def cmd_deposits(message: Message, session_factory: async_sessionmaker) -> None:
    async with session_factory() as session:
        facts, _ = await compare_views.load_for_bot(session)
    await message.answer(compare_views.deposits_text(facts))


@router.message(Command("savings"))
async def cmd_savings(message: Message, session_factory: async_sessionmaker) -> None:
    async with session_factory() as session:
        facts, _ = await compare_views.load_for_bot(session)
    await message.answer(compare_views.savings_text(facts))


@router.message(Command("changes"))
async def cmd_changes(message: Message, command: CommandObject, session_factory: async_sessionmaker) -> None:
    from bankintel.bot.changes_views import changes_text, parse_days

    try:
        days = parse_days(command.args)
    except ValueError as exc:
        await message.answer(escape(str(exc)))
        return
    async with session_factory() as session:
        await message.answer(await changes_text(session, days))


_report_lock = asyncio.Lock()


@router.message(Command("report"))
async def cmd_report(message: Message, session_factory: async_sessionmaker) -> None:
    import tempfile
    from pathlib import Path

    from bankintel.reports.dataset import DatasetError
    from bankintel.reports.service import generate_reports

    if _report_lock.locked():
        await message.answer("Отчёт уже формируется, дождитесь окончания.")
        return
    async with _report_lock:
        await message.answer("Формирую отчёты (PDF, HTML, PPTX, XLSX) из текущих данных…")
        with tempfile.TemporaryDirectory() as tmp:
            try:
                async with session_factory() as session:
                    bundle = await generate_reports(session, Path(tmp))
            except DatasetError as exc:
                await message.answer("Отчёт не сформирован:\n" + escape(str(exc))[:3500])
                return
            m = bundle.dataset["meta"]
            caption = (
                f"Набор данных {bundle.dataset_id}. Демо-прототип: банков с данными {m['banks_with_data']} из {m['banks_total']}, "
                f"без Сбербанка; доступность в ЛНР не подтверждена."
            )
            for fmt, path in bundle.paths.items():
                await message.answer_document(FSInputFile(path), caption=f"{fmt.upper()} · {caption}")


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
