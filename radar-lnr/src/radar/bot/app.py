"""Бот (aiogram 3) + планировщик (APScheduler). Один процесс."""
from __future__ import annotations

import asyncio
import logging
from html import escape

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from ..config import get_env, get_settings, load_channels, setup_logging
from ..db import DB
from ..llm.client import LLMAuthError, LLMError, make_client
from ..pipeline import run_once
from .auth import WhitelistMiddleware
from .sender import broadcast, recipients, safe_send

log = logging.getLogger(__name__)
router = Router()
_run_lock = asyncio.Lock()   # два запуска одновременно не нужны


class Ctx:
    bot: Bot
    db: DB


ctx = Ctx()


async def notify_admin(text: str) -> None:
    """Служебные уведомления — только админу, в общий дайджест не идут."""
    admin = get_env().admin_user_id
    if admin:
        await safe_send(ctx.bot, admin, text)
    else:
        log.error("ADMIN_USER_ID не задан, служебное сообщение потеряно: %s", text)


async def do_digest(hours: float | None = None, to_admin_only: bool = False) -> str:
    """Полный цикл + рассылка. Возвращает короткий статус."""
    env = get_env()
    if _run_lock.locked():
        return "Запуск уже идёт, подожди."
    async with _run_lock:
        try:
            res = await run_once(ctx.db, hours=hours)
        except LLMAuthError as e:
            msg = f"🔑 Проблема с LLM-ключом: {escape(str(e))}\nПроверь .env и запусти scripts/check_llm.py"
            log.error(msg)
            await notify_admin(msg)
            return "Ошибка доступа к LLM"
        except Exception as e:
            log.exception("запуск упал")
            await notify_admin(f"❌ Запуск упал: {escape(repr(e))[:500]}")
            return "Запуск упал, подробности админу"

    if res.channel_errors:  # недоступные каналы — админу, подробно
        lines = "\n".join(f"• {k}: {escape(v)}" for k, v in list(res.channel_errors.items())[:20])
        await notify_admin(f"⚠️ Недоступно каналов: {len(res.channel_errors)}\n{lines}")
    chats = [env.admin_user_id] if to_admin_only else recipients(env.chat_ids, env.allowed_ids, ctx.db.dm_muted())
    delivered = await broadcast(ctx.bot, chats, res.digest)
    ok = sum(delivered.values())
    return f"Готово: событий {len(res.events)}, доставлено {ok}/{len(chats)}. {res.cost.summary() if res.cost else ''}"


# ---------------- команды ----------------
@router.message(Command("start"))
async def cmd_start(m: Message):
    await m.answer("📡 <b>Радар ЛНР</b>\nРаз в 4 часа присылаю дайджест новостей региона.\n\n"
                   "/myid — твой user_id\n/channels — каналы\n/stats — статистика\n"
                   "/mute, /unmute — отключить/включить дайджест в личку\n/digest — запустить сейчас (админ)")


@router.message(Command("myid"))
async def cmd_myid(m: Message):
    await m.answer(f"Твой user_id: <code>{m.from_user.id}</code>")


@router.message(Command("digest"))
async def cmd_digest(m: Message, command: CommandObject):
    if m.from_user.id != get_env().admin_user_id:
        await m.answer("Эта команда только для администратора.")
        return
    hours = float(command.args) if command.args and command.args.replace(".", "", 1).isdigit() else None
    await m.answer("Запускаю… это займёт несколько минут ⏳")
    await m.answer(escape(await do_digest(hours)))


@router.message(Command("mute"))
async def cmd_mute(m: Message):
    ctx.db.set_dm(m.from_user.id, False)
    await m.answer("🔕 Дайджест в личку отключён. В группу он приходит как раньше. Вернуть: /unmute")


@router.message(Command("unmute"))
async def cmd_unmute(m: Message):
    ctx.db.set_dm(m.from_user.id, True)
    await m.answer("🔔 Дайджест в личку включён.")


@router.message(Command("channels"))
async def cmd_channels(m: Message):
    chs, last = load_channels(), ctx.db.last_run()
    import json
    errs = json.loads(last["channel_errors"]) if last and last.get("channel_errors") else {}
    txt = f"Каналов в channels.yaml: <b>{len(chs)}</b>"
    if last:
        txt += f"\nПоследний запуск: {last['started_at'][:16]} UTC, статус {last['status']}"
    if errs:
        txt += f"\n\n⚠️ Не читаются ({len(errs)}):\n" + "\n".join(f"• @{k}: {escape(v)}" for k, v in list(errs.items())[:25])
    elif last:
        txt += "\n✅ В последнем запуске все каналы читались."
    await m.answer(txt)


@router.message(Command("stats"))
async def cmd_stats(m: Message):
    s = ctx.db.stats()
    cost = f"${s['cost_usd']:.2f}" if s["cost_usd"] is not None else "н/д"
    await m.answer(f"📊 Запусков: {s['runs']}\nПостов в базе: {s['posts']}\nСобытий: {s['events']}\nLLM всего: {cost}")


# ---------------- запуск ----------------
async def startup_check() -> None:
    """При старте проверяем LLM тестовым запросом; при проблеме — понятное сообщение в лог и админу."""
    env = get_env()
    try:
        client = make_client(env)
        await client.complete(env.model_filter, "Отвечай одним словом.", "ок?", max_tokens=10)
        log.info("Проверка LLM пройдена")
    except LLMError as e:
        log.error("Проверка LLM не пройдена: %s", e)
        await notify_admin(f"🔑 Проверка LLM при старте не пройдена:\n{escape(str(e))}")


async def run_bot() -> None:
    setup_logging()
    env, cfg = get_env(), get_settings()
    token = env.bot_token.get_secret_value()
    if not token:
        raise SystemExit("BOT_TOKEN не задан в .env")
    ctx.bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    ctx.db = DB(env.data_path / "radar.db")
    dp = Dispatcher()
    router.message.outer_middleware(WhitelistMiddleware(env.allowed_ids))
    dp.include_router(router)

    sched = AsyncIOScheduler(timezone=cfg["digest"]["timezone"])
    sched.add_job(do_digest, IntervalTrigger(hours=cfg["digest"]["every_hours"]), id="digest",
                  max_instances=1, coalesce=True, misfire_grace_time=600)
    sched.start()
    log.info("Бот запущен. Whitelist: %d пользователей, чатов для дайджеста: %d", len(env.allowed_ids), len(env.chat_ids))
    await startup_check()
    try:
        await dp.start_polling(ctx.bot)
    finally:
        sched.shutdown(wait=False)
        await ctx.bot.session.close()
