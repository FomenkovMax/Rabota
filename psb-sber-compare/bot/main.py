#!/usr/bin/env python3
"""Telegram-бот сравнения розничных продуктов Сбера с конкурентами.

Запуск:
    python -m bot.main

Нужны переменные окружения (или файл .env рядом с проектом):
    BOT_TOKEN         токен от @BotFather
    BOT_ALLOWED_IDS   telegram id через запятую, кому открыт доступ
    ANTHROPIC_API_KEY ключ для AI-консультанта

Про доступ. Бот показывает внутреннюю аналитику, поэтому отвечает только
тем, кто перечислен в BOT_ALLOWED_IDS. Пустой список означает «никому»:
для такого содержимого открытый по умолчанию доступ — плохая настройка
по умолчанию, лучше явная ошибка при старте.
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiogram import Bot, Dispatcher, F  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.enums import ParseMode  # noqa: E402
from aiogram.filters import Command  # noqa: E402
from aiogram.types import BufferedInputFile, CallbackQuery, Message  # noqa: E402

from bot import keyboards as kb  # noqa: E402
from bot import service  # noqa: E402

log = logging.getLogger("bot")

WELCOME = (
    "<b>Сравнение розничных продуктов</b>\n"
    "Сбер против конкурентов в Луганской Народной Республике.\n\n"
    "Выбери, что показать."
)


def load_dotenv(path: Path) -> None:
    """Читает .env без внешних зависимостей."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def allowed_ids() -> set[int]:
    raw = os.environ.get("BOT_ALLOWED_IDS", "")
    out: set[int] = set()
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk.isdigit():
            out.add(int(chunk))
    return out


ALLOWED: set[int] = set()


def permitted(user_id: int | None) -> bool:
    return user_id is not None and user_id in ALLOWED


dp = Dispatcher()

# Кого ждём с текстовым вопросом к консультанту: user_id.
awaiting_question: set[int] = set()


@dp.message(Command("start", "menu"))
async def cmd_start(message: Message) -> None:
    if not permitted(message.from_user.id if message.from_user else None):
        await message.answer(
            "Доступ к этому боту ограничен.\n"
            f"Твой Telegram ID: <code>{message.from_user.id}</code>\n"
            "Передай его администратору, чтобы он добавил тебя в список."
        )
        return
    awaiting_question.discard(message.from_user.id)
    await message.answer(WELCOME, reply_markup=kb.main_menu())


@dp.message(Command("id"))
async def cmd_id(message: Message) -> None:
    await message.answer(f"Твой Telegram ID: <code>{message.from_user.id}</code>")


@dp.callback_query(F.data == "menu")
async def on_menu(call: CallbackQuery) -> None:
    awaiting_question.discard(call.from_user.id)
    await call.message.edit_text(WELCOME, reply_markup=kb.main_menu())
    await call.answer()


# --- сравнение -------------------------------------------------------------

@dp.callback_query(F.data.startswith("cmp:"))
async def on_compare(call: CallbackQuery) -> None:
    if not permitted(call.from_user.id):
        await call.answer("Доступ закрыт", show_alert=True)
        return

    code = call.data.split(":", 1)[1]
    await call.answer()
    await call.message.edit_text("Считаю…")

    try:
        text = await asyncio.to_thread(service.compare_text, code)
    except Exception as exc:                      # noqa: BLE001
        log.exception("Сравнение %s не удалось", code)
        text = f"Не получилось посчитать: {html.escape(str(exc))[:400]}"

    await call.message.edit_text(text, reply_markup=kb.back_to_menu(),
                                 disable_web_page_preview=True)


# --- выгрузка --------------------------------------------------------------

@dp.callback_query(F.data == "export:menu")
async def on_export_menu(call: CallbackQuery) -> None:
    await call.message.edit_text("В каком виде выгрузить свод?",
                                 reply_markup=kb.export_menu())
    await call.answer()


@dp.callback_query(F.data.startswith("export:"))
async def on_export(call: CallbackQuery) -> None:
    if not permitted(call.from_user.id):
        await call.answer("Доступ закрыт", show_alert=True)
        return

    fmt = call.data.split(":", 1)[1]
    if fmt == "menu":
        return

    await call.answer()
    await call.message.edit_text("Готовлю файлы…")

    try:
        files = await asyncio.to_thread(service.export_files, fmt)
    except Exception as exc:                      # noqa: BLE001
        log.exception("Выгрузка %s не удалась", fmt)
        await call.message.edit_text(
            f"Не получилось выгрузить: {html.escape(str(exc))[:400]}",
            reply_markup=kb.back_to_menu())
        return

    if not files:
        await call.message.edit_text(
            "Выгружать нечего — сначала обнови данные.",
            reply_markup=kb.back_to_menu())
        return

    for path in files:
        data = Path(path).read_bytes()
        await call.message.answer_document(
            BufferedInputFile(data, filename=Path(path).name))

    await call.message.answer("Готово.", reply_markup=kb.main_menu())


# --- AI-консультант --------------------------------------------------------

AI_PRESETS = {
    "weak": "Где мы проигрываем сильнее всего и что из этого требует решения в первую очередь?",
    "promo": "Сравни акции банков: чего нам не хватает в продуктовом маркетинге?",
    "week": "Что изменилось за последнюю неделю и на что обратить внимание?",
}


@dp.callback_query(F.data == "ai:menu")
async def on_ai_menu(call: CallbackQuery) -> None:
    await call.message.edit_text(
        "Спроси совета по собранным цифрам.\n"
        "<i>Консультант отвечает только по нашим данным и не додумывает условия банков.</i>",
        reply_markup=kb.ai_menu())
    await call.answer()


@dp.callback_query(F.data == "ai:free")
async def on_ai_free(call: CallbackQuery) -> None:
    awaiting_question.add(call.from_user.id)
    await call.message.edit_text(
        "Напиши вопрос одним сообщением — отвечу по собранным данным.",
        reply_markup=kb.back_to_menu())
    await call.answer()


@dp.callback_query(F.data.startswith("ai:"))
async def on_ai_preset(call: CallbackQuery) -> None:
    if not permitted(call.from_user.id):
        await call.answer("Доступ закрыт", show_alert=True)
        return

    key = call.data.split(":", 1)[1]
    if key in ("menu", "free"):
        return

    await call.answer()
    await call.message.edit_text("Думаю…")
    await _answer_ai(call.message, AI_PRESETS.get(key, ""))


@dp.message(F.text & ~F.text.startswith("/"))
async def on_free_question(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else None
    if not permitted(user_id) or user_id not in awaiting_question:
        return

    awaiting_question.discard(user_id)
    thinking = await message.answer("Думаю…")
    await _answer_ai(thinking, message.text or "")


async def _answer_ai(target: Message, question: str) -> None:
    try:
        text = await asyncio.to_thread(service.ai_answer, question)
    except Exception as exc:                      # noqa: BLE001
        log.exception("Консультант не ответил")
        text = f"Консультант недоступен: {html.escape(str(exc))[:400]}"

    for chunk in _split(text):
        await target.answer(chunk, disable_web_page_preview=True)
    await target.answer("Ещё вопрос?", reply_markup=kb.ai_menu())


def _split(text: str, limit: int = 3800) -> list[str]:
    """Телеграм не принимает сообщения длиннее 4096 символов."""
    if len(text) <= limit:
        return [text]
    parts, current = [], ""
    for paragraph in text.split("\n\n"):
        if len(current) + len(paragraph) + 2 > limit:
            if current:
                parts.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        parts.append(current)
    return parts


# --- обновление данных -----------------------------------------------------

@dp.callback_query(F.data == "collect:menu")
async def on_collect_menu(call: CallbackQuery) -> None:
    await call.message.edit_text(
        "Сбор занимает несколько минут — бот напишет, когда закончит.",
        reply_markup=kb.collect_menu())
    await call.answer()


@dp.callback_query(F.data.startswith("collect:"))
async def on_collect(call: CallbackQuery) -> None:
    if not permitted(call.from_user.id):
        await call.answer("Доступ закрыт", show_alert=True)
        return

    code = call.data.split(":", 1)[1]
    if code == "menu":
        return

    await call.answer("Запустил сбор")
    await call.message.edit_text("Собираю данные. Это займёт несколько минут…")

    try:
        report = await asyncio.to_thread(service.collect, code)
    except Exception as exc:                      # noqa: BLE001
        log.exception("Сбор %s не удался", code)
        report = f"Сбор не удался: {html.escape(str(exc))[:400]}"

    await call.message.answer(report, reply_markup=kb.main_menu())


# --- запуск ----------------------------------------------------------------

async def run() -> None:
    global ALLOWED

    load_dotenv(ROOT / ".env")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "Не задан BOT_TOKEN.\n"
            "Получи токен у @BotFather и положи в .env:\n"
            "  BOT_TOKEN=123456:AA...\n"
            "  BOT_ALLOWED_IDS=123456789"
        )

    ALLOWED = allowed_ids()
    if not ALLOWED:
        raise SystemExit(
            "Не задан BOT_ALLOWED_IDS — список тех, кому открыт бот.\n"
            "Бот показывает внутреннюю аналитику, поэтому без списка не стартует.\n"
            "Свой id узнаешь у @userinfobot, дальше в .env:\n"
            "  BOT_ALLOWED_IDS=123456789,987654321"
        )

    log.info("Доступ открыт %s пользователям", len(ALLOWED))
    bot = Bot(token=token,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit) as exc:
        if isinstance(exc, SystemExit) and exc.code:
            print(exc.code, file=sys.stderr)
            raise
        print("\nБот остановлен.")
