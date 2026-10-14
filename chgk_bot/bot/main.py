"""Telegram-бот «Что? Где? Когда?» — соло-тренировка с минутой на размышление."""
import asyncio
import html
import logging
import os
import time
from dataclasses import dataclass, field

from aiogram import BaseMiddleware, Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .cards import ASSETS
from .config import PKG_DIR, load_settings
from .generator import generate
from .judge import judge
from .llm import make_client
from .storage import QuestionBank, Stats

log = logging.getLogger("chgk")
cfg = load_settings()
bank = QuestionBank(cfg.data_dir / "questions.json", seed=PKG_DIR / "seed_questions.json")
stats = Stats(cfg.data_dir / "stats.sqlite")

llm = None
if cfg.anthropic_key:
    llm = make_client(cfg.anthropic_key, os.getenv("ANTHROPIC_AUTH_MODE", "x-api-key"))

bot = Bot(cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# Закрытый доступ: ALLOWED_IDS="123,456" — только эти пользователи (и админ). Пусто — бот открыт всем.
ALLOWED = {int(x) for x in os.getenv("ALLOWED_IDS", "").replace(" ", "").split(",") if x.isdigit()}


def is_allowed(user_id: int) -> bool:
    return not ALLOWED or user_id in ALLOWED or user_id == cfg.admin_id


class Guard(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user and not is_allowed(user.id):
            if isinstance(event, Message):
                await event.answer("Бот приватный: доступ только для команды.")
            elif isinstance(event, CallbackQuery):
                await event.answer("Бот приватный", show_alert=True)
            return None
        return await handler(event, data)


dp.message.outer_middleware(Guard())
dp.callback_query.outer_middleware(Guard())


@dataclass
class Session:
    q: dict
    phase: str = "think"  # think -> answer -> judging
    task: asyncio.Task | None = None
    timer_msg_id: int | None = None
    timer_is_anim: bool = False  # таймер — подпись к анимации с лошадкой, а не текстовое сообщение
    started: float = field(default_factory=time.time)


sessions: dict[int, Session] = {}


def kb(*rows: tuple[str, str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d)] for t, d in rows])


MENU = kb(("🎲 Новый вопрос", "new"), ("📊 Моя статистика", "stats"))


def bar(left: int, total: int, width: int = 12) -> str:
    filled = round(width * left / total)
    return "🟨" * filled + "⬛" * (width - filled)


async def photo(chat_id: int, kind: str, caption: str, markup=None) -> Message:
    return await bot.send_photo(chat_id, FSInputFile(ASSETS / f"{kind}.png"), caption=caption, reply_markup=markup)


HORSE = ASSETS / "horse.mp4"
TICK = 10  # как часто обновлять отсчёт, сек (Telegram не любит частые правки)


async def timer_send(s: Session, chat_id: int, text: str, markup) -> None:
    """Таймер минуты: анимация с бегущей лошадкой (подпись = отсчёт); без файла — обычный текст."""
    if HORSE.exists():
        msg = await bot.send_animation(chat_id, FSInputFile(HORSE), caption=text, reply_markup=markup)
        s.timer_is_anim = True
    else:
        msg = await bot.send_message(chat_id, text, reply_markup=markup)
    s.timer_msg_id = msg.message_id


async def timer_edit(s: Session, chat_id: int, text: str, markup=None) -> None:
    if s.timer_is_anim:
        await bot.edit_message_caption(chat_id=chat_id, message_id=s.timer_msg_id, caption=text, reply_markup=markup)
    else:
        await bot.edit_message_text(text, chat_id, s.timer_msg_id, reply_markup=markup)


# ---------- команды ----------

@dp.message(Command("start", "help"))
async def cmd_start(m: Message):
    text = (
        "Привет! Это тренажёр для знатоков 🧠\n\n"
        "<b>Как играем:</b>\n"
        f"1. Я присылаю вопрос в стиле «Что? Где? Когда?».\n"
        f"2. У тебя <b>{cfg.think_seconds} секунд</b> на размышление — я отсчитываю время.\n"
        f"3. Потом ещё {cfg.answer_seconds} сек, чтобы отправить ответ одним сообщением.\n"
        "4. Я оцениваю ответ (✅ верно / 🟡 почти = ½ балла / ❌ мимо) и даю <b>разбор логики</b>.\n\n"
        "Главное в ЧГК — не знать, а <i>слушать вопрос</i>: ищи зацепки в формулировке."
    )
    await photo(m.chat.id, "welcome", text, MENU)


@dp.message(Command("question"))
async def cmd_question(m: Message):
    await start_question(m.chat.id, m.from_user.id)


@dp.message(Command("stats"))
async def cmd_stats(m: Message):
    await send_stats(m.chat.id, m.from_user.id)


@dp.message(Command("gen"))
async def cmd_gen(m: Message, command: CommandObject):
    """Админ: /gen [N] [тема] — сгенерировать вопросы через Claude и добавить в базу."""
    if m.from_user.id != cfg.admin_id:
        return
    if llm is None:
        await m.answer("Не задан ANTHROPIC_API_KEY.")
        return
    args = (command.args or "").split(maxsplit=1)
    n = int(args[0]) if args and args[0].isdigit() else 5
    topic = args[1] if len(args) > 1 else (args[0] if args and not args[0].isdigit() else None)
    await m.answer(f"⏳ Генерирую {n} вопросов (автор + проверка критиком)…")
    try:
        good, rejected = await generate(llm, os.getenv("GEN_MODEL") or cfg.model, n=min(n, 10), topic=topic)
    except Exception as e:
        log.exception("generate failed")
        await m.answer(f"Не вышло: {html.escape(str(e))}")
        return
    added = bank.add(good)
    rej = "\n".join(html.escape(r) for r in rejected) or "—"
    await m.answer(f"✅ Добавлено: {added} (всего в базе: {len(bank.items)})\n\nОтбраковано критиком:\n{rej}")


async def send_stats(chat_id: int, user_id: int) -> None:
    s = stats.summary(user_id)
    if not s["played"]:
        await bot.send_message(chat_id, "Пока нет сыгранных вопросов. Начнём?", reply_markup=MENU)
        return
    pct = round(100 * s["points"] / s["played"])
    await bot.send_message(
        chat_id,
        f"📊 <b>Твоя статистика</b>\nВопросов: {s['played']}\n✅ Верно: {int(s['correct'])}\n"
        f"🟡 Почти: {int(s['close'])}\nОчки: {s['points']:g} из {s['played']} ({pct}%)",
        reply_markup=MENU,
    )


# ---------- кнопки ----------

@dp.callback_query(F.data == "new")
async def cb_new(c: CallbackQuery):
    await c.answer()
    await start_question(c.message.chat.id, c.from_user.id)


@dp.callback_query(F.data == "stats")
async def cb_stats(c: CallbackQuery):
    await c.answer()
    await send_stats(c.message.chat.id, c.from_user.id)


@dp.callback_query(F.data == "ready")
async def cb_ready(c: CallbackQuery):
    """«Готов отвечать» — досрочно закончить минуту."""
    s = sessions.get(c.from_user.id)
    if not s or s.phase != "think":
        await c.answer("Минута уже закончилась")
        return
    await c.answer()
    s.task.cancel()
    s.task = asyncio.create_task(answer_phase(c.message.chat.id, c.from_user.id, s, early=True))


@dp.callback_query(F.data == "skip")
async def cb_skip(c: CallbackQuery):
    s = sessions.get(c.from_user.id)
    if not s or s.phase == "judging":
        await c.answer()
        return
    await c.answer()
    s.task.cancel()
    await finish(c.message.chat.id, c.from_user.id, s, None)


# ---------- игровой цикл ----------

async def start_question(chat_id: int, user_id: int) -> None:
    if sessions.get(user_id):
        await bot.send_message(chat_id, "Ты ещё не закончил текущий вопрос. Отправь ответ или нажми «Сдаюсь».")
        return
    q, fresh = bank.pick(stats.seen(user_id))
    if q is None:
        await bot.send_message(chat_id, "База вопросов пуста 😕")
        return
    s = Session(q=q)
    sessions[user_id] = s
    note = "" if fresh else "\n<i>Ты прошёл все вопросы — начинаем повторы.</i>"
    stars = "★" * int(q.get("difficulty", 3)) + "☆" * (5 - int(q.get("difficulty", 3)))
    await photo(chat_id, "question", f"<b>Внимание, вопрос!</b>  {stars}\n\n{html.escape(q['text'])}{note}")
    await timer_send(
        s, chat_id, f"⏳ Осталось <b>{cfg.think_seconds}</b> сек\n{bar(cfg.think_seconds, cfg.think_seconds)}",
        kb(("✋ Готов отвечать", "ready"), ("🏳 Сдаюсь", "skip")),
    )
    s.task = asyncio.create_task(think_phase(chat_id, user_id, s))


async def think_phase(chat_id: int, user_id: int, s: Session) -> None:
    total, step = cfg.think_seconds, TICK
    end = s.started + total
    try:
        while (left := round(end - time.time())) > 0:
            await asyncio.sleep(min(step, left))
            left = max(0, round(end - time.time()))
            if left <= 0:
                break
            markup = kb(("✋ Готов отвечать", "ready"), ("🏳 Сдаюсь", "skip"))
            tail = "  ⚠️" if left <= 10 else ""
            try:
                await timer_edit(s, chat_id, f"⏳ Осталось <b>{left}</b> сек{tail}\n{bar(left, total)}", markup)
            except Exception:
                pass
        await answer_phase(chat_id, user_id, s, early=False)
    except asyncio.CancelledError:
        pass


async def answer_phase(chat_id: int, user_id: int, s: Session, early: bool) -> None:
    s.phase = "answer"
    try:
        await timer_edit(s, chat_id, "⏱ Минута закончилась" if not early else "✋ Ответ готов")
    except Exception:
        pass
    await bot.send_message(
        chat_id, f"⏰ <b>{'Время!' if not early else 'Принято.'}</b> Отправь ответ одним сообщением "
        f"(у тебя {cfg.answer_seconds} сек).", reply_markup=kb(("🏳 Сдаюсь", "skip")),
    )
    try:
        await asyncio.sleep(cfg.answer_seconds)
    except asyncio.CancelledError:
        return
    if sessions.get(user_id) is s and s.phase == "answer":
        await finish(chat_id, user_id, s, None)


@dp.message(F.text & ~F.text.startswith("/"))
async def on_text(m: Message):
    s = sessions.get(m.from_user.id)
    if not s or s.phase == "judging":
        return
    if s.task:  # ответил раньше времени тоже принимаем
        s.task.cancel()
    await finish(m.chat.id, m.from_user.id, s, m.text)


async def finish(chat_id: int, user_id: int, s: Session, answer: str | None) -> None:
    if s.phase == "judging":
        return
    s.phase = "judging"
    q = s.q
    if answer is None:
        verdict_kind, score, comment = "wrong", 0.0, "Ответ не был дан."
    else:
        await bot.send_chat_action(chat_id, "typing")
        v = await judge(llm, cfg.model, q, answer)
        verdict_kind, score, comment = v.level, v.score, v.comment
    stats.record(user_id, q["id"], score, answer)
    if sessions.get(user_id) is s:
        sessions.pop(user_id)

    head = {"correct": "✅ <b>Верно!</b> +1", "close": "🟡 <b>Почти.</b> +½", "wrong": "❌ <b>Не засчитано.</b>"}[verdict_kind]
    parts = [head]
    if answer:
        parts.append(f"Твой ответ: <i>{html.escape(answer[:200])}</i>")
    if comment:
        parts.append(html.escape(comment))
    parts.append(f"\n<b>Правильный ответ:</b> {html.escape(q['answer'])}")
    if q.get("accepted"):
        parts.append(f"Зачёт: {html.escape(', '.join(q['accepted']))}")
    parts.append(f"\n<b>Разбор:</b>\n<blockquote expandable>{html.escape(q['explanation'])}</blockquote>")
    if q.get("author"):  # вопросы чужие — всегда показываем автора и источник
        where = f" · {html.escape(q['pack_title'])}" if q.get("pack_title") else ""
        parts.append(f"<i>Автор вопроса: {html.escape(q['author'])}{where}</i>")
    text = "\n".join(parts)
    # у подписи к фото лимит 1024 символа — длинный разбор отправляем отдельным сообщением
    if len(text) <= 1000:
        await photo(chat_id, verdict_kind, text, MENU)
    else:
        await photo(chat_id, verdict_kind, "\n".join(parts[:2]))
        await bot.send_message(chat_id, "\n".join(parts[2:]), reply_markup=MENU)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if llm is None:
        log.warning("ANTHROPIC_API_KEY не задан: оценка только по точному совпадению, /gen недоступен")
    log.info("Вопросов в базе: %d", len(bank.items))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
