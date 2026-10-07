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
from aiogram.client.session.middlewares.base import BaseRequestMiddleware  # noqa: E402
from aiogram.exceptions import TelegramBadRequest  # noqa: E402
from aiogram.types import (BufferedInputFile, CallbackQuery,  # noqa: E402
                           InlineKeyboardMarkup, Message)

from bot import keyboards as kb  # noqa: E402
from bot import service  # noqa: E402

log = logging.getLogger("bot")

WELCOME = (
    "<b>Сравнение розничных продуктов</b>\n"
    "Сбер против конкурентов в Луганской Народной Республике.\n\n"
    "🔄 <b>Обновить все банки</b> — свежий сбор с сайтов, 50–60 мин\n"
    "🏦 <b>Сравнить</b> — светофор Сбера против одного банка\n"
    "📂 <b>По категориям</b> — место Сбера и аргументы для клиента\n"
    "📊 <b>Выгрузить свод</b> — Excel, PDF, HTML или данные для BI\n"
    "🤖 <b>AI-консультант</b> — совет по собранным цифрам\n"
    "🔁 <b>Обновить один банк</b> — быстрее, остальные из прошлого сбора\n"
    "🧪 <b>Аудит качества</b> — сверка цифр с сайтами и баллы по критериям"
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

# Идёт ли сбор: второй поверх первого делил бы с ним машину и базу.
collecting = asyncio.Lock()

# Кого ждём с эмодзи после /emoji_id.
awaiting_emoji: set[int] = set()

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


@dp.message(Command("emoji_id"))
async def on_emoji_id(message: Message) -> None:
    if not permitted(message.from_user.id if message.from_user else None):
        return
    awaiting_emoji.add(message.from_user.id)
    await message.answer("Отправь одним сообщением эмодзи из набора — "
                         "отвечу id каждого. Их вставляют в config/bot_icons.yaml.")


@dp.message(lambda m: m.from_user is not None and m.from_user.id in awaiting_emoji)
async def on_emoji_sample(message: Message) -> None:
    awaiting_emoji.discard(message.from_user.id)
    found = [e for e in (message.entities or []) if e.type == "custom_emoji"]
    if not found:
        await message.answer("Эмодзи из набора не нашёл. Обычные эмодзи id не имеют — "
                             "нужны именно из набора. Попробуй ещё раз: /emoji_id")
        return
    lines = [f"{i}. <code>{e.custom_emoji_id}</code>" for i, e in enumerate(found, 1)]
    await message.answer("id по порядку:\n" + "\n".join(lines))


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


# --- по категориям -----------------------------------------------------------

@dp.callback_query(F.data == "cat:menu")
async def on_category_menu(call: CallbackQuery) -> None:
    await call.message.edit_text(
        "Какую категорию разобрать? Покажу место Сбера по программам, лучшие "
        "базовые ставки банков и ставки на особых условиях.",
        reply_markup=kb.category_menu())
    await call.answer()


@dp.callback_query(F.data.startswith("cat:"))
async def on_category(call: CallbackQuery) -> None:
    if not permitted(call.from_user.id):
        await call.answer("Доступ закрыт", show_alert=True)
        return
    code = call.data.split(":", 1)[1]
    await call.answer()
    await call.message.edit_text("Считаю…")
    try:
        text = await asyncio.to_thread(service.category_text, code)
    except Exception as exc:                      # noqa: BLE001
        log.exception("Категория %s не посчиталась", code)
        text = f"Не получилось посчитать: {html.escape(str(exc))[:400]}"
    chunks = _split(text)
    for chunk in chunks[:-1]:
        await call.message.answer(chunk, disable_web_page_preview=True)
    await call.message.edit_text(chunks[-1], reply_markup=kb.category_actions(code),
                                 disable_web_page_preview=True)


@dp.callback_query(F.data.startswith("script:"))
async def on_client_script(call: CallbackQuery) -> None:
    if not permitted(call.from_user.id):
        await call.answer("Доступ закрыт", show_alert=True)
        return
    code = call.data.split(":", 1)[1]
    await call.answer()
    thinking = await call.message.answer("Готовлю аргументы…")
    try:
        text = await asyncio.to_thread(service.client_script, code)
    except Exception as exc:                      # noqa: BLE001
        log.exception("Скрипт %s не получился", code)
        text = f"Не получилось: {html.escape(str(exc))[:400]}"
    chunks = _split(text)
    await thinking.edit_text(chunks[0], disable_web_page_preview=True)
    for chunk in chunks[1:]:
        await call.message.answer(chunk, disable_web_page_preview=True)
    await call.message.answer("Что дальше?", reply_markup=kb.category_actions(code))


# --- автоаудит ---------------------------------------------------------------

@dp.callback_query(F.data == "audit:menu")
async def on_audit_menu(call: CallbackQuery) -> None:
    await call.message.edit_text(
        "Автоаудит заново открывает страницы банков и сверяет с ними цифры отчёта, "
        "проверяет охват и сопоставимость и ставит баллы по формулам. Занимает "
        "10–20 минут. Независимый LLM-аудит — то же плюс оценка моделью по "
        "собранному пакету.",
        reply_markup=kb.audit_menu())
    await call.answer()


@dp.callback_query(F.data.startswith("audit:"))
async def on_audit(call: CallbackQuery) -> None:
    if not permitted(call.from_user.id):
        await call.answer("Доступ закрыт", show_alert=True)
        return
    action = call.data.split(":", 1)[1]
    if action == "menu":
        return
    if action == "last":
        await call.answer()
        files = await asyncio.to_thread(service.latest_audit_files)
        if not files:
            await call.message.edit_text("Аудит ещё не запускался.",
                                         reply_markup=kb.audit_menu())
            return
        for path in files:
            await call.message.answer_document(
                BufferedInputFile(Path(path).read_bytes(), filename=Path(path).name))
        await call.message.answer("Готово.", reply_markup=kb.main_menu())
        return

    # Аудит открывает страницы браузером — как сбор, поэтому не параллельно с ним.
    if collecting.locked():
        await call.answer("Идёт сбор или аудит — дождись сообщения о завершении",
                          show_alert=True)
        return
    async with collecting:
        await call.answer("Запустил аудит")
        await call.message.edit_text("🧪 Аудит идёт, 10–20 минут — пришлю отчёт.")
        try:
            process = await asyncio.create_subprocess_exec(
                *service.audit_command(llm=action == "llm"), cwd=str(service.ROOT),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            tail: list[str] = []
            assert process.stdout is not None
            async for raw in process.stdout:
                line = raw.decode("utf-8", "replace").rstrip()
                if line:
                    print(line, flush=True)
                    tail = (tail + [line])[-30:]
            returncode = await process.wait()
            summary = service.audit_summary(returncode, tail)
        except Exception as exc:                  # noqa: BLE001
            log.exception("Аудит не удался")
            summary, returncode = f"Аудит не удался: {html.escape(str(exc))[:400]}", 1

    await call.message.answer(summary)
    if returncode == 0:
        for path in await asyncio.to_thread(service.latest_audit_files):
            await call.message.answer_document(
                BufferedInputFile(Path(path).read_bytes(), filename=Path(path).name))
    await call.message.answer("Что дальше?", reply_markup=kb.main_menu())


# --- обновление данных -----------------------------------------------------

@dp.callback_query(F.data == "collect:menu")
async def on_collect_menu(call: CallbackQuery) -> None:
    await call.message.edit_text(
        "Какой банк обновить? Один банк — 5–12 минут, остальные банки "
        "останутся из прошлого сбора. Бот напишет, когда закончит.",
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

    # Два сбора разом делили бы одну машину и одну базу — второй ждёт.
    if collecting.locked():
        await call.answer("Сбор уже идёт — дождись сообщения о завершении",
                          show_alert=True)
        return

    async with collecting:
        await call.answer("Запустил сбор")
        if code == "all":
            await call.message.edit_text(
                "🔄 Обновляю все банки. Это 25–35 минут — напишу, когда закончу.\n"
                "Ботом можно пользоваться и сейчас: выгрузка покажет прошлый сбор.")
        else:
            await call.message.edit_text(
                "🔁 Обновляю банк. Это 5–12 минут — напишу, когда закончу.")

        try:
            report = await _collect_in_process(code)
        except Exception as exc:                  # noqa: BLE001
            log.exception("Сбор %s не удался", code)
            report = f"Сбор не удался: {html.escape(str(exc))[:400]}"

    await call.message.answer(report, reply_markup=kb.main_menu())


async def _collect_in_process(code: str) -> str:
    """Сбор отдельным процессом: если его убьют, бот останется жив.

    Строки сбора идут в лог бота как есть — по docker logs видно ход.
    """
    process = await asyncio.create_subprocess_exec(
        *service.collect_command(code), cwd=str(service.ROOT),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    tail: list[str] = []
    assert process.stdout is not None
    async for raw in process.stdout:
        line = raw.decode("utf-8", "replace").rstrip()
        if line:
            print(line, flush=True)
            tail = (tail + [line])[-20:]
    returncode = await process.wait()
    if returncode != 0:
        log.warning("Сбор %s завершился с кодом %s", code, returncode)
    return await asyncio.to_thread(service.collect_summary, code, returncode, tail)


class IconFallback(BaseRequestMiddleware):
    """Если Telegram отказал в значках на кнопках — шлём то же без них.

    Значки из набора разрешены не каждому боту. Без этой страховки отказ
    ломал бы любое меню, и бот переставал бы отвечать на кнопки.
    """

    async def __call__(self, make_request, bot, method):  # type: ignore[override]
        try:
            return await make_request(bot, method)
        except TelegramBadRequest as exc:
            markup = getattr(method, "reply_markup", None)
            used = isinstance(markup, InlineKeyboardMarkup) and any(
                item.icon_custom_emoji_id for row in markup.inline_keyboard for item in row)
            if not used:
                raise
            kb.disable_icons(str(exc)[:200])
            kb.strip_icons(markup)
            return await make_request(bot, method)


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

    # Из некоторых сетей api.telegram.org недоступен напрямую. Тогда
    # соединение идёт через прокси, заданный в BOT_PROXY. На сбор данных
    # с сайтов банков это не влияет — там свои настройки.
    proxy = os.environ.get("BOT_PROXY", "").strip()
    session = None
    if proxy:
        from aiogram.client.session.aiohttp import AiohttpSession  # noqa: PLC0415

        # curl различает socks5 и socks5h тем, кто разрешает имена: сам
        # curl или прокси. aiogram разрешает их через прокси всегда, и
        # схему socks5h не принимает. Схемы с суффиксом приводим к той,
        # которую он понимает, — поведение от этого не меняется.
        for suffix, plain in (("socks5h://", "socks5://"),
                              ("socks4a://", "socks4://")):
            if proxy.lower().startswith(suffix):
                proxy = plain + proxy[len(suffix):]
                break

        log.info("Подключаюсь к Telegram через прокси %s",
                 proxy.split("@")[-1])   # без логина и пароля в логе
        try:
            session = AiohttpSession(proxy=proxy)
        except ValueError as exc:
            raise SystemExit(
                f"Не понимаю адрес прокси в BOT_PROXY: {exc}\n"
                f"Ожидаю вид схема://логин:пароль@адрес:порт, где схема —\n"
                f"socks5, socks4 или http. Например:\n"
                f"  BOT_PROXY=socks5://myuser:mypass@77.83.184.180:8000"
            ) from None

    bot = Bot(token=token, session=session,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    bot.session.middleware(IconFallback())

    # Сетевые и токенные ошибки показываем человеческим текстом: бота
    # ставит на сервер не разработчик, и простыня трейсбека ему ничего
    # не объясняет.
    from aiogram.exceptions import (TelegramNetworkError,  # noqa: PLC0415
                                    TelegramUnauthorizedError)
    try:
        me = await bot.get_me()
        log.info("Бот @%s на связи", me.username)
        await dp.start_polling(bot)
    except TelegramUnauthorizedError:
        raise SystemExit(
            "Telegram отклонил токен.\n"
            "Проверь BOT_TOKEN в .env — его выдаёт @BotFather, "
            "формат «123456:AA…»."
        ) from None
    except TelegramNetworkError as exc:
        hint = ""
        if "CERTIFICATE_VERIFY_FAILED" in str(exc):
            hint = ("\nПохоже на перехват TLS: сеть подменяет сертификаты.\n"
                    "Укажи корневой сертификат своей сети через SSL_CERT_FILE.")
        elif not proxy:
            hint = (
                "\n\nПроверь с сервера, доступен ли Telegram:\n"
                "  curl -s -m 10 -o /dev/null -w '%{http_code}\\n' "
                "https://api.telegram.org\n"
                "Ответ 000 означает, что из этой сети Telegram не открывается.\n"
                "Тогда пропиши прокси в .env и перезапусти бота:\n"
                "  BOT_PROXY=http://логин:пароль@адрес:порт"
            )
        else:
            hint = ("\n\nПрокси задан, но связи нет. Проверь его адрес "
                    "и работоспособность.")
        raise SystemExit(
            f"Нет связи с api.telegram.org.{hint}"
        ) from None
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit) as exc:
        if isinstance(exc, SystemExit) and exc.code:
            print(exc.code, file=sys.stderr)
            raise
        print("\nБот остановлен.")
