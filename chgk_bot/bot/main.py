"""Telegram-бот «Что? Где? Когда?»: соло-тренировка и командная игра по правилам спортивного ЧГК."""
import asyncio
import html
import logging
import os
import re
import time
from dataclasses import dataclass, field

from aiogram import BaseMiddleware, Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .cards import ASSETS
from .config import PKG_DIR, load_settings
from .game import TeamGame, final_summary, tour_line
from .generator import generate
from core.answers import judge
from core.llm import make_client
from core.steps import make_steps, render_steps
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

GROUPS = {"group", "supergroup"}
reads_all = False   # видит ли бот все сообщения группы (выключен Privacy mode в BotFather); определяется при старте


def answer_hint() -> str:
    """Как капитану сдать ответ: обычным сообщением можно, только если у бота выключен Privacy mode."""
    if reads_all:
        return "любым сообщением, реплаем на это сообщение или <code>/o ответ</code>"
    return "реплаем на это сообщение или <code>/o ваш ответ</code>"


# ---------- доступ ----------
# ALLOWED_IDS="1,2"       — кто может пользоваться ботом в личке (и админ всегда)
# ALLOWED_CHATS="-100123" — группы, где играть может любой участник (id группы покажет команда /myid)
# Пусто в обоих — бот открыт всем.

def _ids(name: str) -> set[int]:
    return {int(x) for x in os.getenv(name, "").replace(" ", "").split(",") if x.lstrip("-").isdigit()}


ALLOWED = _ids("ALLOWED_IDS")
ALLOWED_CHATS = _ids("ALLOWED_CHATS")


def is_allowed(user_id: int, chat_id: int | None = None, chat_type: str = "private") -> bool:
    if user_id == cfg.admin_id:
        return True
    if not (ALLOWED or ALLOWED_CHATS):
        return True
    if user_id in ALLOWED:
        return True
    return chat_type in GROUPS and chat_id in ALLOWED_CHATS


class Guard(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        msg = event if isinstance(event, Message) else getattr(event, "message", None)
        chat = getattr(msg, "chat", None)
        chat_id, chat_type = getattr(chat, "id", None), getattr(chat, "type", "private")
        text = (getattr(event, "text", None) or "") if isinstance(event, Message) else ""
        if text.split("@")[0].strip() in ("/myid", "/chatid"):   # ID можно узнать всем: он нужен, чтобы добавить в список
            return await handler(event, data)
        if user and not is_allowed(user.id, chat_id, chat_type):
            log.warning("Отказано в доступе: id=%s username=@%s имя=%s чат=%s", user.id, user.username, user.full_name, chat_id)
            if chat_type in GROUPS:
                return None   # в чужой группе молчим
            if isinstance(event, Message):
                await event.answer("Бот приватный: доступ только для команды.")
            elif isinstance(event, CallbackQuery):
                await event.answer("Бот приватный", show_alert=True)
            return None
        return await handler(event, data)


dp.message.outer_middleware(Guard())
dp.callback_query.outer_middleware(Guard())


# ---------- общие помощники ----------

@dataclass
class Session:
    q: dict
    phase: str = "think"  # think -> answer -> judging
    task: asyncio.Task | None = None
    timer_msg_id: int | None = None
    timer_is_anim: bool = False  # таймер — подпись к анимации с лошадкой, а не текстовое сообщение
    started: float = field(default_factory=time.time)


sessions: dict[int, Session] = {}
games: dict[int, TeamGame] = {}


def kb(*rows: tuple[str, str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d)] for t, d in rows])


MENU = kb(("🎲 Новый вопрос", "new"), ("📊 Моя статистика", "stats"))


def after_kb(qid: str, solo: bool = True) -> InlineKeyboardMarkup:
    rows = [("🧩 Разбор по шагам", f"steps:{qid}")]
    if solo:
        rows += [("🎲 Новый вопрос", "new"), ("📊 Моя статистика", "stats")]
    return kb(*rows)


def hidden() -> set[str]:
    return stats.hidden_ids(cfg.hide_min_answers, cfg.hide_lo, cfg.hide_hi)


def bar(left: int, total: int, width: int = 12) -> str:
    filled = round(width * left / total)
    return "🟨" * filled + "⬛" * (width - filled)


async def photo(chat_id: int, kind: str, caption: str, markup=None) -> Message:
    return await bot.send_photo(chat_id, FSInputFile(ASSETS / f"{kind}.png"), caption=caption, reply_markup=markup)


HORSE = ASSETS / "horse.mp4"
TICK = 10  # как часто обновлять отсчёт, сек (Telegram не любит частые правки)


async def timer_send(s, chat_id: int, text: str, markup) -> None:
    """Таймер минуты: анимация с бегущей лошадкой (подпись = отсчёт); без файла — обычный текст.
    s — Session или TeamGame (нужны поля timer_msg_id, timer_is_anim)."""
    if HORSE.exists():
        msg = await bot.send_animation(chat_id, FSInputFile(HORSE), caption=text, reply_markup=markup)
        s.timer_is_anim = True
    else:
        msg = await bot.send_message(chat_id, text, reply_markup=markup)
    s.timer_msg_id = msg.message_id


async def timer_edit(s, chat_id: int, text: str, markup=None) -> None:
    if s.timer_is_anim:
        await bot.edit_message_caption(chat_id=chat_id, message_id=s.timer_msg_id, caption=text, reply_markup=markup)
    else:
        await bot.edit_message_text(text, chat_id, s.timer_msg_id, reply_markup=markup)


def result_parts(q: dict, head: str, answer: str | None, comment: str, who: str = "Твой ответ") -> list[str]:
    """Текст результата (одинаков для соло и командной игры)."""
    parts = [head]
    if answer:
        parts.append(f"{who}: <i>{html.escape(answer[:200])}</i>")
    if comment:
        parts.append(html.escape(comment))
    parts.append(f"\n<b>Правильный ответ:</b> {html.escape(q['answer'])}")
    if q.get("accepted"):
        parts.append(f"Зачёт: {html.escape(', '.join(q['accepted']))}")
    n, share = stats.rate(q["id"])
    if n >= 3 and share is not None:
        parts.append(f"📊 Этот вопрос берут {round(share * 100)}% (ответов: {n})")
    parts.append(f"\n<b>Разбор автора:</b>\n<blockquote expandable>{html.escape(q['explanation'])}</blockquote>")
    if q.get("author"):  # вопросы чужие — всегда показываем автора и источник
        where = f" · {html.escape(q['pack_title'])}" if q.get("pack_title") else ""
        parts.append(f"<i>Автор вопроса: {html.escape(q['author'])}{where}</i>")
    return parts


async def send_result(chat_id: int, kind: str, parts: list[str], markup) -> None:
    text = "\n".join(parts)
    # у подписи к фото лимит 1024 символа — длинный разбор отправляем отдельным сообщением
    if len(text) <= 1000:
        await photo(chat_id, kind, text, markup)
    else:
        await photo(chat_id, kind, "\n".join(parts[:2]))
        await bot.send_message(chat_id, "\n".join(parts[2:]), reply_markup=markup)


# ---------- общие команды ----------

@dp.message(Command("start", "help"))
async def cmd_start(m: Message):
    if m.chat.type in GROUPS:
        await m.answer(
            "Привет, знатоки! 🎩 <b>Командная игра по правилам спортивного ЧГК</b>\n\n"
            f"/game — начать игру ({cfg.team_tours} тура по {cfg.team_per_tour} вопросов; можно /game 2x10)\n"
            "/captain — сменить капитана (ответом на сообщение игрока)\n"
            "/o ответ — капитан сдаёт ответ (или реплаем на сообщение бота)\n"
            "/stop — закончить игру\n"
            "/stats — статистика команды\n"
            "/myid — ID этого чата и твой ID"
        )
        return
    text = (
        "Привет! Это тренажёр для знатоков 🧠\n\n"
        "<b>Как играем:</b>\n"
        f"1. Я присылаю вопрос в стиле «Что? Где? Когда?».\n"
        f"2. У тебя <b>{cfg.think_seconds} секунд</b> на размышление — я отсчитываю время.\n"
        f"3. Потом ещё {cfg.answer_seconds} сек, чтобы отправить ответ одним сообщением.\n"
        "4. Я оцениваю ответ (✅ верно / 🟡 почти = ½ балла / ❌ мимо) и даю <b>разбор</b>; "
        "кнопка «🧩 Разбор по шагам» покажет цепочку рассуждения.\n\n"
        "Командная игра — в группе: добавь меня в чат и отправь /game.\n"
        "Главное в ЧГК — не знать, а <i>слушать вопрос</i>: ищи зацепки в формулировке."
    )
    await photo(m.chat.id, "welcome", text, MENU)


@dp.message(Command("myid", "chatid"))
async def cmd_myid(m: Message):
    await m.answer(f"Твой ID: <code>{m.from_user.id}</code>\nID этого чата: <code>{m.chat.id}</code>")


@dp.message(Command("stats"))
async def cmd_stats(m: Message):
    if m.chat.type in GROUPS:
        await send_stats(m.chat.id, m.chat.id, "Статистика команды", with_menu=False)
    else:
        await send_stats(m.chat.id, m.from_user.id)


@dp.message(Command("qstats"))
async def cmd_qstats(m: Message):
    """Админ: какие вопросы лёгкие, а какие сложные (по первой попытке каждого игрока/команды)."""
    if m.from_user.id != cfg.admin_id:
        return
    rows = [(qid, n, k) for qid, (n, k) in stats.question_rates().items() if n >= 3 and bank.get(qid)]
    if not rows:
        await m.answer("Пока мало данных: нужно хотя бы 3 ответа на вопрос.")
        return
    rows.sort(key=lambda r: r[2] / r[1])

    def line(r) -> str:
        qid, n, k = r
        return f"{round(100 * k / n)}% ({n}) — {html.escape(str(bank.get(qid)['answer'])[:40])}"

    hid = hidden()
    text = (
        f"📊 <b>Статистика вопросов</b> (вопросов с ≥3 ответами: {len(rows)})\n\n"
        "🔥 <b>Самые сложные:</b>\n" + "\n".join(line(r) for r in rows[:5]) +
        "\n\n🟢 <b>Самые лёгкие:</b>\n" + "\n".join(line(r) for r in rows[::-1][:5]) +
        f"\n\n🙈 Скрыто из игры (вне {round(cfg.hide_lo * 100)}–{round(cfg.hide_hi * 100)}% при ≥{cfg.hide_min_answers} ответах): {len(hid)}"
    )
    await m.answer(text)


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


async def send_stats(chat_id: int, user_id: int, title: str = "Твоя статистика", with_menu: bool = True) -> None:
    s = stats.summary(user_id)
    menu = MENU if with_menu else None
    if not s["played"]:
        await bot.send_message(chat_id, "Пока нет сыгранных вопросов. Начнём?", reply_markup=menu)
        return
    pct = round(100 * s["points"] / s["played"])
    await bot.send_message(
        chat_id,
        f"📊 <b>{title}</b>\nВопросов: {s['played']}\n✅ Верно: {int(s['correct'])}\n"
        f"🟡 Почти: {int(s['close'])}\nОчки: {s['points']:g} из {s['played']} ({pct}%)",
        reply_markup=menu,
    )


# ---------- разбор по шагам (соло и команда) ----------

@dp.callback_query(F.data.startswith("steps:"))
async def cb_steps(c: CallbackQuery):
    q = bank.get(c.data.split(":", 1)[1])
    if not q:
        await c.answer("Вопрос не найден", show_alert=True)
        return
    await c.answer("Готовлю разбор…")
    data = q.get("steps")
    if not data and llm is not None:
        await bot.send_chat_action(c.message.chat.id, "typing")
        data = await make_steps(llm, os.getenv("STEPS_MODEL") or cfg.model, q)
        if data:
            bank.set_steps(q["id"], data)
    await bot.send_message(c.message.chat.id, render_steps(q, data))


# ---------- соло: кнопки ----------

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


@dp.message(Command("question"), F.chat.type == "private")
async def cmd_question(m: Message):
    await start_question(m.chat.id, m.from_user.id)


# ---------- соло: игровой цикл ----------

async def start_question(chat_id: int, user_id: int) -> None:
    if sessions.get(user_id):
        await bot.send_message(chat_id, "Ты ещё не закончил текущий вопрос. Отправь ответ или нажми «Сдаюсь».")
        return
    q, fresh = bank.pick(stats.seen(user_id), hidden())
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
    await send_result(chat_id, verdict_kind, result_parts(q, head, answer, comment), after_kb(q["id"]))


# ---------- командная игра ----------

def is_captain(g: TeamGame, user) -> bool:
    return user.id == g.captain_id or user.id == cfg.admin_id


def parse_game_args(args: str | None) -> tuple[int, int]:
    """«/game 2x10» -> (2, 10); по умолчанию — из настроек (3 тура по 12)."""
    m = re.match(r"\s*(\d+)\s*[xх×*]\s*(\d+)", args or "", flags=re.I)
    tours, per = (int(m.group(1)), int(m.group(2))) if m else (cfg.team_tours, cfg.team_per_tour)
    return max(1, min(tours, 6)), max(1, min(per, 20))


@dp.message(Command("game", "stop", "captain", "o"), F.chat.type == "private")
async def team_only_in_groups(m: Message):
    await m.answer("Командная игра работает в групповом чате: добавь меня в чат команды и отправь /game.")


@dp.message(Command("game"), F.chat.type.in_(GROUPS))
async def cmd_game(m: Message, command: CommandObject):
    if m.chat.id in games:
        await m.answer("В этом чате уже идёт игра. Завершить: /stop")
        return
    tours, per = parse_game_args(command.args)
    seen = stats.seen(m.chat.id)
    queue = bank.choose(tours * per, seen, hidden())
    if not queue:
        await m.answer("База вопросов пуста 😕")
        return
    g = TeamGame(chat_id=m.chat.id, captain_id=m.from_user.id, captain_name=m.from_user.full_name, queue=queue, per_tour=per)
    games[m.chat.id] = g
    fresh = sum(1 for q in queue if q["id"] not in seen)
    note = "" if fresh == len(queue) else f"\n<i>Новых для вас вопросов: {fresh} из {len(queue)}, остальные повторяются.</i>"
    short = f"\n<i>В базе хватило только на {len(queue)} вопросов.</i>" if len(queue) < tours * per else ""
    await bot.send_message(
        m.chat.id,
        f"🎩 <b>Командная игра!</b> {g.tours} тура(ов) по {per} вопросов, всего {g.total}.\n"
        f"Капитан: <b>{html.escape(g.captain_name)}</b> (передать: /captain ответом на сообщение игрока).\n\n"
        f"<b>Правила как в спортивном ЧГК:</b>\n"
        f"• {cfg.think_seconds} секунд на обсуждение, потом ответ сдаёт только капитан: {answer_hint()} "
        f"({cfg.team_answer_seconds} сек после «Время!»)\n"
        f"• очко даётся только за верный ответ, «почти» не считается\n"
        f"• после каждого тура — итог тура{note}{short}",
        reply_markup=kb(("▶️ Начать игру", "tnext")),
    )


@dp.callback_query(F.data == "tnext")
async def cb_tnext(c: CallbackQuery):
    g = games.get(c.message.chat.id)
    if not g:
        await c.answer("Игра не идёт. Начать: /game", show_alert=True)
        return
    if not is_captain(g, c.from_user):
        await c.answer(f"Решает капитан: {g.captain_name}", show_alert=True)
        return
    if g.phase not in ("lobby", "between"):
        await c.answer("Вопрос уже идёт")
        return
    await c.answer()
    g.phase = "think"
    await team_ask(g)


async def team_ask(g: TeamGame) -> None:
    q = g.current
    stars = "★" * int(q.get("difficulty", 3)) + "☆" * (5 - int(q.get("difficulty", 3)))
    size = len(g.tour_slice(g.tour))
    await photo(
        g.chat_id, "question",
        f"<b>Тур {g.tour} · вопрос {g.number_in_tour} из {size}</b>  {stars}\n\n{html.escape(q['text'])}",
    )
    g.started = time.time()
    await timer_send(g, g.chat_id, f"⏳ Осталось <b>{cfg.think_seconds}</b> сек\n{bar(cfg.think_seconds, cfg.think_seconds)}", _team_timer_kb())
    g.task = asyncio.create_task(team_think(g))


def _team_timer_kb() -> InlineKeyboardMarkup:
    return kb(("✋ Готовы отвечать", "tready"), ("🏳 Пас", "tskip"))


async def team_think(g: TeamGame) -> None:
    total, end = cfg.think_seconds, g.started + cfg.think_seconds
    try:
        while (left := round(end - time.time())) > 0:
            await asyncio.sleep(min(TICK, left))
            left = max(0, round(end - time.time()))
            if left <= 0:
                break
            tail = "  ⚠️" if left <= 10 else ""
            try:
                await timer_edit(g, g.chat_id, f"⏳ Осталось <b>{left}</b> сек{tail}\n{bar(left, total)}", _team_timer_kb())
            except Exception:
                pass
        await team_answer_phase(g, early=False)
    except asyncio.CancelledError:
        pass


async def team_answer_phase(g: TeamGame, early: bool) -> None:
    g.phase = "answer"
    try:
        await timer_edit(g, g.chat_id, "⏱ Минута закончилась" if not early else "✋ Команда готова")
    except Exception:
        pass
    msg = await bot.send_message(
        g.chat_id,
        f"⏰ <b>{'Время!' if not early else 'Принято.'}</b> Капитан <b>{html.escape(g.captain_name)}</b>, сдайте ответ: "
        f"{answer_hint()} (у вас {cfg.team_answer_seconds} сек).",
        reply_markup=kb(("🏳 Пас", "tskip")),
    )
    g.answer_msg_id = msg.message_id
    try:
        await asyncio.sleep(cfg.team_answer_seconds)
    except asyncio.CancelledError:
        return
    if games.get(g.chat_id) is g and g.phase == "answer":
        await team_finish(g, None)


@dp.callback_query(F.data == "tready")
async def cb_tready(c: CallbackQuery):
    g = games.get(c.message.chat.id)
    if not g or g.phase != "think":
        await c.answer("Минута уже закончилась")
        return
    if not is_captain(g, c.from_user):
        await c.answer(f"Решает капитан: {g.captain_name}", show_alert=True)
        return
    await c.answer()
    g.task.cancel()
    g.task = asyncio.create_task(team_answer_phase(g, early=True))


@dp.callback_query(F.data == "tskip")
async def cb_tskip(c: CallbackQuery):
    g = games.get(c.message.chat.id)
    if not g or g.phase not in ("think", "answer"):
        await c.answer()
        return
    if not is_captain(g, c.from_user):
        await c.answer(f"Решает капитан: {g.captain_name}", show_alert=True)
        return
    await c.answer()
    if g.task:
        g.task.cancel()
    await team_finish(g, None)


async def accept_team_answer(m: Message, text: str) -> None:
    g = games.get(m.chat.id)
    if not g or g.phase not in ("think", "answer"):
        return
    if not is_captain(g, m.from_user):
        await m.reply(f"Ответ сдаёт капитан: {html.escape(g.captain_name)}")
        return
    if g.task:
        g.task.cancel()
    await team_finish(g, text)


@dp.message(Command("o"), F.chat.type.in_(GROUPS))
async def cmd_o(m: Message, command: CommandObject):
    text = (command.args or "").strip()
    if not text:
        await m.reply("Напишите ответ после команды: /o ответ")
        return
    await accept_team_answer(m, text)


@dp.message(F.reply_to_message, F.text, ~F.text.startswith("/"), F.chat.type.in_(GROUPS))
async def on_team_reply(m: Message):
    g = games.get(m.chat.id)
    if g and m.reply_to_message.message_id in (g.answer_msg_id, g.timer_msg_id):
        await accept_team_answer(m, m.text)


@dp.message(F.text, ~F.text.startswith("/"), F.chat.type.in_(GROUPS))
async def on_team_plain(m: Message):
    """Обычное сообщение капитана после «Время!» — это ответ (работает, если у бота выключен Privacy mode)."""
    g = games.get(m.chat.id)
    if g and g.phase == "answer" and m.from_user.id == g.captain_id:
        await accept_team_answer(m, m.text)


async def team_finish(g: TeamGame, answer: str | None) -> None:
    if g.phase == "judging":
        return
    g.phase = "judging"
    q = g.current
    kind = "wrong"
    if answer is None:
        comment = "Ответ не сдан."
    else:
        await bot.send_chat_action(g.chat_id, "typing")
        v = await judge(llm, cfg.model, q, answer)
        kind, comment = v.level, v.comment
    correct = kind == "correct"
    g.results[g.idx] = correct
    stats.record(g.chat_id, q["id"], 1.0 if correct else 0.0, answer, mode="team")

    head = {
        "correct": "✅ <b>Верно!</b> +1 знатокам",
        "close": "🟡 <b>Почти, но в бланк не засчитывается.</b>",
        "wrong": "❌ <b>Не засчитано.</b>",
    }[kind]
    parts = result_parts(q, head, answer, comment, who="Ответ команды")
    parts.insert(1, f"Счёт: <b>{g.score()} из {g.answered()}</b>")
    await send_result(g.chat_id, kind, parts, after_kb(q["id"], solo=False))

    extra: list[str] = []
    if g.is_last_in_tour():
        extra.append("🔔 <b>Конец тура</b>\n" + tour_line(g, g.tour))
    if g.is_last():
        g.phase = "finished"
        games.pop(g.chat_id, None)
        await bot.send_message(g.chat_id, "\n\n".join(extra + [final_summary(g)]))
        return
    g.idx += 1
    g.phase = "between"
    nxt = f"Следующий — тур {g.tour}, вопрос {g.number_in_tour}." if extra else f"Следующий вопрос: {g.number_in_tour} из {len(g.tour_slice(g.tour))}."
    await bot.send_message(
        g.chat_id, ("\n".join(extra) + "\n\n" if extra else "") + f"{nxt} Готовы? Нажимает капитан.",
        reply_markup=kb(("▶️ Следующий вопрос", "tnext")),
    )


@dp.message(Command("stop"), F.chat.type.in_(GROUPS))
async def cmd_stop(m: Message):
    g = games.get(m.chat.id)
    if not g:
        await m.answer("Игра не идёт. Начать: /game")
        return
    if not is_captain(g, m.from_user):
        await m.reply(f"Остановить игру может капитан: {html.escape(g.captain_name)}")
        return
    if g.task:
        g.task.cancel()
    games.pop(m.chat.id, None)
    await m.answer(final_summary(g, stopped=True))


@dp.message(Command("captain"), F.chat.type.in_(GROUPS))
async def cmd_captain(m: Message):
    g = games.get(m.chat.id)
    if not g:
        await m.answer("Игра не идёт. Начать: /game")
        return
    target = m.reply_to_message.from_user if m.reply_to_message and m.reply_to_message.from_user else None
    if target is not None and getattr(target, "is_bot", False):
        target = None
    if target is not None:
        if not is_captain(g, m.from_user):
            await m.reply("Передать роль может только капитан.")
            return
    else:
        if g.phase in ("think", "answer", "judging"):
            await m.reply("Во время вопроса менять капитана нельзя.")
            return
        target = m.from_user
    g.captain_id, g.captain_name = target.id, target.full_name
    await m.answer(f"🎖 Капитан: <b>{html.escape(target.full_name)}</b>")


# ---------- соло: ответ текстом (только в личке) ----------

@dp.message(F.text & ~F.text.startswith("/"), F.chat.type == "private")
async def on_text(m: Message):
    s = sessions.get(m.from_user.id)
    if not s or s.phase == "judging":
        return
    if s.task:  # ответил раньше времени тоже принимаем
        s.task.cancel()
    await finish(m.chat.id, m.from_user.id, s, m.text)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if llm is None:
        log.warning("ANTHROPIC_API_KEY не задан: оценка только по точному совпадению, /gen и разбор по шагам недоступны")
    global reads_all
    try:
        reads_all = bool((await bot.get_me()).can_read_all_group_messages)
    except Exception:
        log.exception("get_me не удался")
    log.info("Вопросов в базе: %d", len(bank.items))
    log.info("Бот читает все сообщения групп: %s", "да (Privacy mode выключен)" if reads_all else "нет (только команды и reply)")
    restricted = ALLOWED or ALLOWED_CHATS
    log.info("Доступ: %s", f"только люди {sorted(ALLOWED)} и группы {sorted(ALLOWED_CHATS)} (+админ)" if restricted
             else "ОТКРЫТ ВСЕМ (ALLOWED_IDS и ALLOWED_CHATS не заданы)")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
