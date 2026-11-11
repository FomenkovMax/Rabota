"""Бот (aiogram 3) + планировщик (APScheduler). Один процесс."""
from __future__ import annotations

import asyncio
import logging
from html import escape

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ..config import get_env, get_settings, load_channels, setup_logging
from ..db import DB
from ..llm.client import LLMAuthError, LLMBalanceError, LLMError, make_client
from ..enrichment.service import Enricher, build_adapters
from ..daily import card_text, header_text, keyboard, pick_events, send_cards, tokens_line_for_day
from ..pipeline import run_once
from ..report.export import export_files
from ..report.feedback import feedback_report, parse_vote
from ..report.pdf import make_onepager
from ..report.excel import cards_workbook
from .auth import WhitelistMiddleware
from .inn_file import MAX_INNS, SUPPORTED, parse_inn_file
from ..report.snapshot import build_report, parse_hours
from .schedule import is_silent_slot, needs_catchup
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


async def alert_once(key: str, hours: float, text: str) -> None:
    """Служебное уведомление админу не чаще раза в `hours` часов (чтобы не спамить каждые 4 часа)."""
    from datetime import datetime, timedelta, timezone
    last = ctx.db.get_meta(key)
    if last and datetime.now(timezone.utc) - datetime.fromisoformat(last) < timedelta(hours=hours):
        return
    ctx.db.set_meta(key, datetime.now(timezone.utc).isoformat(timespec="seconds"))
    await notify_admin(text)


async def _run_guarded(hours: float | None, build_outputs: bool):
    """run_once с понятной реакцией на ошибки. -> (результат | None, текст-ошибка | None)."""
    try:
        return await run_once(ctx.db, hours=hours, build_outputs=build_outputs), None
    except LLMBalanceError as e:
        log.error("токены закончились: %s", e)
        await alert_once("alert_balance_empty", 12, f"💳 <b>Токены закончились</b>: {escape(str(e))}\n"
                         "Сбор новостей остановлен. Пополни баланс у продавца — запуски возобновятся сами.")
        return None, "Токены закончились — сбор не выполнен"
    except LLMAuthError as e:
        msg = f"🔑 Проблема с LLM-ключом: {escape(str(e))}\nПроверь .env и запусти scripts/check_llm.py"
        log.error(msg)
        await notify_admin(msg)
        return None, "Ошибка доступа к LLM"
    except Exception as e:
        log.exception("запуск упал")
        await notify_admin(f"❌ Запуск упал: {escape(repr(e))[:500]}")
        return None, "Запуск упал, подробности админу"


async def _after_run(res) -> None:
    """Служебные сообщения админу после любого запуска: недоступные каналы и низкий баланс."""
    if res.channel_errors:
        lines = "\n".join(f"• {k}: {escape(v)}" for k, v in list(res.channel_errors.items())[:20])
        await alert_once("alert_channels", 24, f"⚠️ Недоступно каналов: {len(res.channel_errors)}\n{lines}")
    warn = get_settings()["llm"].get("low_balance_warn")
    if res.tokens_left is not None and warn and res.tokens_left < warn:
        await alert_once("alert_low_balance", 24, f"⚠️ Токенов мало: осталось {res.tokens_left:,}".replace(",", " ")
                         + ". Пополни баланс, иначе сбор остановится.")


def _today(tz: str) -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo(tz)).date().isoformat()


async def do_collect(scheduled: bool = True) -> str:
    """Фоновый тихий сбор: новости попадают в базу, получателям ничего не уходит (отправка — раз в день)."""
    if _run_lock.locked() and not scheduled:
        return "Запуск уже идёт, подожди."
    async with _run_lock:
        res, err = await _run_guarded(None, build_outputs=False)
    if res is None:
        return err
    await _after_run(res)
    return f"Сбор: событий {len(res.events)}, постов {res.posts_new}. {res.cost.summary() if res.cost else ''}"


async def do_daily(preview: bool = False) -> str:
    """Ежедневная рассылка (15:00 МСК): сначала свежий сбор, затем всё, что ещё не отправляли, одним заходом.
    preview=True — только админу и без пометки «отправлено» (для проверки)."""
    from datetime import datetime, timedelta, timezone
    env, cfg = get_env(), get_settings()
    d = cfg["digest"]
    async with _run_lock:
        res, err = await _run_guarded(None, build_outputs=False)
        if res is not None:
            await _after_run(res)
        elif not ctx.db.unsent_events():
            return err
        until = datetime.now(timezone.utc)
        events = ctx.db.unsent_events()
        # окно «с» — самое раннее неотправленное событие (но не больше 3 суток назад)
        since = until - timedelta(hours=24)
        left = res.tokens_left if res else None
        dash_min = d.get("dashboard_min_score", 2)
        pool = [e for e in events if e["relevance_score"] >= dash_min]
        cards, _rest = pick_events(pool, d["min_score"], d.get("daily_max_cards", 15))
        failed = len(ctx.db.channel_errors_since((until - timedelta(hours=24)).isoformat(timespec="seconds")))
        head = header_text(cards, len(pool), since, until, d["timezone"], failed,
                           tokens_line_for_day(ctx.db, left, cfg["llm"].get("low_balance_warn")), d["min_score"])
        files: list = []
        exports = env.data_path / "exports"
        if pool:
            files = export_files(pool, since, until, exports, d["timezone"])
            try:
                if (pdf := await make_onepager(pool, since, until, exports, d["min_score"], d["timezone"])):
                    files.insert(0, pdf)
            except Exception as e:
                log.warning("PDF «Главное» не создан: %s: %s", type(e).__name__, e)
    dm_ids = env.allowed_ids if d.get("send_dm", True) else set()
    chats = [env.admin_user_id] if preview else recipients(env.chat_ids, dm_ids, ctx.db.dm_muted())
    delivered = await broadcast(ctx.bot, chats, head, files)
    ok_chats = [c for c, v in delivered.items() if v]
    await send_cards(ctx.bot, ok_chats, cards)
    if not preview and ok_chats:       # помечаем отправленным только если хоть кто-то получил
        ctx.db.mark_sent([e["id"] for e in events])
        ctx.db.set_meta("last_daily_date", _today(d["timezone"]))
    return f"Дайджест дня: карточек {len(cards)}, в дашборде {len(pool)}, доставлено {len(ok_chats)}/{len(chats)}"


async def do_digest(hours: float | None = None, to_admin_only: bool = False, scheduled: bool = False) -> str:
    """Полный цикл + рассылка. scheduled=True — плановый запуск по расписанию: он НЕ пропускается, если в этот
    момент идёт ручной /digest (ждёт своей очереди), и ночные слоты (silent_hours) рассылает без звука.
    Ручной /digest всегда со звуком."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    env = get_env()
    cfg_d = get_settings()["digest"]
    slot_hour = datetime.now(ZoneInfo(cfg_d["timezone"])).hour      # час слота фиксируем в момент старта запуска
    if _run_lock.locked() and not scheduled:
        return "Запуск уже идёт, подожди."
    async with _run_lock:
        try:
            res = await run_once(ctx.db, hours=hours)
        except LLMBalanceError as e:
            log.error("токены закончились: %s", e)
            await alert_once("alert_balance_empty", 12, f"💳 <b>Токены закончились</b>: {escape(str(e))}\n"
                             "Дайджест не сформирован. Пополни баланс у продавца — запуски возобновятся сами.")
            return "Токены закончились — дайджест не сформирован"
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
    dm_ids = env.allowed_ids if cfg_d.get("send_dm", True) else set()
    chats = [env.admin_user_id] if to_admin_only else recipients(env.chat_ids, dm_ids, ctx.db.dm_muted())
    silent = scheduled and is_silent_slot(slot_hour, cfg_d.get("silent_hours"))   # 00:00 и 04:00 — без звука
    delivered = await broadcast(ctx.bot, chats, res.digest, res.files, silent=silent)
    ok = sum(delivered.values())
    warn = get_settings()["llm"].get("low_balance_warn")
    if res.tokens_left is not None and warn and res.tokens_left < warn:   # заранее предупредить админа
        await alert_once("alert_low_balance", 24, f"⚠️ Токенов мало: осталось {res.tokens_left:,}".replace(",", " ")
                         + ". Пополни баланс, иначе дайджесты остановятся.")
    return f"Готово: событий {len(res.events)}, доставлено {ok}/{len(chats)}. {res.cost.summary() if res.cost else ''}"


# ---------------- команды ----------------
@router.message(Command("start", "help", "menu"))
async def cmd_start(m: Message):
    await m.answer("📡 <b>Радар ЛНР</b>\nРаз в день в 15:00 (МСК) присылаю новости региона с кнопками оценки полезности 1–5.\n\n"
                   "/report [часы] — дайджест за N часов (по умолчанию 24) из сохранённого, без трат токенов\n"
                   "/myid — твой user_id\n/chatid — ID чата (для группы)\n/inn — карточка по ИНН (или пришли файл)\n/channels — каналы\n/stats — статистика и токены\n"
                   "/mute, /unmute — отключить/включить дайджест в личку\n"
                   "/digest [часы] — свежий сбор новостей прямо сейчас, только админу (тратит токены)\n"
                   "/daily — репетиция ежедневной рассылки только админу; /feedback — статистика оценок (админ)\n"
                   "В группе добавляй имя бота: /report@Radar_Bank_Bot 24")


@router.message(Command("myid"))
async def cmd_myid(m: Message):
    await m.answer(f"Твой user_id: <code>{m.from_user.id}</code>")


@router.message(Command("chatid"))
async def cmd_chatid(m: Message):
    """Напиши в группе — бот покажет её ID (его нужно вписать в DIGEST_CHAT_IDS)."""
    await m.answer(f"ID этого чата: <code>{m.chat.id}</code>")


@router.message(Command("digest"))
async def cmd_digest(m: Message, command: CommandObject):
    if m.from_user.id != get_env().admin_user_id:
        await m.answer("Эта команда только для администратора.")
        return
    hours = parse_hours(command.args)       # окно в часах — первое слово аргументов, остальное игнорируем
    await m.answer("Запускаю… это займёт несколько минут ⏳")
    await m.answer(escape(await do_digest(hours, to_admin_only=True)))   # рассылка всем — только ежедневная в 15:00


@router.message(Command("daily"))
async def cmd_daily(m: Message):
    """Репетиция ежедневной рассылки: приходит только админу, ничего не помечается отправленным."""
    if m.from_user.id != get_env().admin_user_id:
        await m.answer("Эта команда только для администратора.")
        return
    await m.answer("Готовлю дайджест дня (только тебе, без пометки «отправлено»)… ⏳")
    await m.answer(escape(await do_daily(preview=True)))


@router.message(Command("feedback"))
async def cmd_feedback(m: Message):
    if m.from_user.id != get_env().admin_user_id:
        await m.answer("Эта команда только для администратора.")
        return
    await m.answer(feedback_report(ctx.db.feedback_rows()))


def _can_vote(c: CallbackQuery) -> bool:
    env = get_env()
    uid = c.from_user.id
    in_group = c.message is not None and c.message.chat.id in set(env.chat_ids) and c.message.chat.id < 0
    return uid in env.allowed_ids or uid == env.admin_user_id or in_group


@router.callback_query(F.data.startswith("v:"))
async def on_vote(c: CallbackQuery):
    """Нажатие кнопки 1–5 под новостью: пишем оценку (один голос на человека, можно переголосовать)."""
    vote = parse_vote(c.data)
    if not vote or not _can_vote(c):
        await c.answer("Недоступно", show_alert=False)
        return
    eid, score = vote
    ev = ctx.db.get_event(eid)
    if not ev:
        await c.answer("Эта новость уже удалена")
        return
    ctx.db.set_vote(eid, c.from_user.id, score)
    avg, n = ctx.db.vote_stats(eid)
    await c.answer(f"Спасибо! Оценка {score}")
    try:
        await c.message.edit_text(card_text(ev, avg, n, score), reply_markup=keyboard(eid, score),
                                  disable_web_page_preview=True)
    except Exception as e:      # «message is not modified» и т.п. — оценка уже сохранена
        log.info("карточку не обновили: %s", e)


@router.message(Command("report"))
async def cmd_report(m: Message, command: CommandObject):
    """Дайджест за N часов (по умолчанию 24) из СОХРАНЁННОГО: без сбора и без LLM, токены не тратятся.
    Ответ уходит в тот чат, где команду написали. Доступна всем участникам группы дайджеста."""
    hours = parse_hours(command.args, default=24.0)
    await m.answer(f"Собираю отчёт за {hours:g} ч… ⏳")
    try:
        bal = await make_client(get_env()).get_balance()
    except LLMError:
        bal = None
    text, files, n = await build_report(ctx.db, hours, get_settings(), get_env().data_path / "exports", bal)
    if not await safe_send(ctx.bot, m.chat.id, text, files):
        await m.answer("Не удалось отправить отчёт.")


@router.message(Command("mute"))
async def cmd_mute(m: Message):
    ctx.db.set_dm(m.from_user.id, False)
    await m.answer("🔕 Дайджест в личку отключён. В группу он приходит как раньше. Вернуть: /unmute")


@router.message(Command("unmute"))
async def cmd_unmute(m: Message):
    ctx.db.set_dm(m.from_user.id, True)
    await m.answer("🔔 Дайджест в личку включён.")


def _enricher() -> Enricher:
    return Enricher(ctx.db, build_adapters(get_env(), get_settings()), get_settings()["enrichment"]["cache_ttl_days"])


def _card_text(res) -> str:
    if res.status != "found":
        return {"not_found": "🔎 Не найдено.", "disabled": "⚙️ Обогащение выключено: не задан DADATA_API_KEY.",
                "needs_review": "❓ Требует проверки"}.get(res.status, "❌ " + res.message) + (f" {escape(res.message)}" if res.status == "not_found" else "")
    c, n = res.card, "н/д"
    f = lambda v: escape(", ".join(v)) if isinstance(v, list) and v else escape(str(v)) if v else n  # noqa: E731
    return (f"🏢 <b>{f(c.name_full)}</b>\nИНН {f(c.inn)} · ОГРН {f(c.ogrn)}\nСтатус: {f(c.status)}\nОКВЭД: {f(c.okved)}\n"
            f"Адрес: {f(c.address)}\n👤 ЛПР: {f(c.director)}{(', ' + escape(c.director_post)) if c.director_post else ''}\n"
            f"Учредители: {f(c.founders)}\nЧисленность: {f(c.employees)}\nТелефон: {f(c.phones)} · Email: {f(c.emails)}")


@router.message(Command("inn"))
async def cmd_inn(m: Message, command: CommandObject):
    if not command.args:
        await m.answer("Использование: <code>/inn 7707083893</code>\nИли пришли файл .xlsx/.csv/.txt со списком ИНН (до 50).")
        return
    res = await _enricher().lookup_inn(command.args.strip())
    await m.answer(_card_text(res))
    if res.status == "needs_review":
        await m.answer(escape("\n".join(f"{i}. {c.name_full} (ИНН {c.inn})" for i, c in enumerate(res.candidates, 1))))


@router.message(F.document)
async def on_document(m: Message):
    """Пакетная проверка: файл со списком ИНН -> один Excel со всеми карточками."""
    doc = m.document
    if not (doc.file_name or "").lower().endswith(SUPPORTED):
        await m.answer("Нужен файл .xlsx, .csv или .txt со списком ИНН.")
        return
    if (doc.file_size or 0) > 2_000_000:
        await m.answer("Файл слишком большой (макс. 2 МБ).")
        return
    buf = await ctx.bot.download(doc)
    try:
        valid, invalid, truncated = parse_inn_file(doc.file_name, buf.read())
    except Exception as e:
        await m.answer(f"Не смог прочитать файл: {escape(str(e))}")
        return
    if not valid and not invalid:
        await m.answer("В файле не нашлось ИНН (10 или 12 цифр).")
        return
    await m.answer(f"Нашёл ИНН: {len(valid)}" + (f" (взял первые {MAX_INNS})" if truncated else "")
                   + (f", с ошибкой в номере: {len(invalid)}" if invalid else "") + ". Проверяю… ⏳")
    enr, items = _enricher(), []
    for inn in valid:
        items.append((inn, await enr.lookup_inn(inn)))
        await asyncio.sleep(0.15)
    from ..enrichment.base import LookupResult
    for inn in invalid:   # битые ИНН не выбрасываем молча — показываем в файле
        items.append((inn, LookupResult("error", message="ИНН не прошёл проверку контрольной суммы")))
    await m.answer_document(BufferedInputFile(cards_workbook(items), filename="inn_cards.xlsx"),
                            caption=f"Готово: найдено {sum(r.status == 'found' for _, r in items)} из {len(items)}")


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
    try:
        bal = await make_client(get_env()).get_balance()
    except LLMError:
        bal = None
    left = f"{bal:,}".replace(",", " ") if bal is not None else "н/д"
    await m.answer(f"📊 Запусков: {s['runs']}\nПостов в базе: {s['posts']}\nСобытий: {s['events']}\n"
                   f"LLM всего: {cost}\n🪙 Токенов осталось: {left}")


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
    router.message.outer_middleware(WhitelistMiddleware(env.allowed_ids, set(env.chat_ids)))
    dp.include_router(router)

    dcfg = cfg["digest"]
    sched = AsyncIOScheduler(timezone=dcfg["timezone"])
    hours_list = dcfg.get("schedule_hours")
    # По часам на часах (00:00, 04:00, 08:00…), а не «через 4 часа после старта» — расписание не сдвигается перезапусками
    trigger = (CronTrigger(hour=",".join(str(h) for h in hours_list), minute=0, timezone=dcfg["timezone"])
               if hours_list else IntervalTrigger(hours=dcfg["every_hours"]))
    # фоновый тихий сбор (в базу), получателям ничего не уходит
    sched.add_job(do_collect, trigger, id="collect", max_instances=1, coalesce=True, misfire_grace_time=600)
    # ежедневная рассылка: раз в день, в daily_hour:00 по Москве
    daily_hour, daily_min = int(dcfg.get("daily_hour", 15)), int(dcfg.get("daily_minute", 0))
    sched.add_job(do_daily, CronTrigger(hour=daily_hour, minute=daily_min, timezone=dcfg["timezone"]), id="daily",
                  max_instances=1, coalesce=True, misfire_grace_time=3600)
    sched.start()
    # Если слот пропущен (простой/перезапуск в момент слота) — один раз наверстываем сразу, не ждём следующего
    from datetime import datetime, timedelta, timezone
    if needs_catchup(ctx.db.last_success(), datetime.now(timezone.utc), hours_list, dcfg["every_hours"]):
        sched.add_job(do_collect, DateTrigger(run_date=datetime.now(timezone.utc) + timedelta(seconds=15)),
                      id="catchup")
        log.info("Прошлый успешный сбор слишком давно — наверстаю через 15 секунд")
    # Дневную рассылку наверстываем, только если она уже когда-то была, сегодня ещё нет, а время вышло
    from zoneinfo import ZoneInfo
    now_l = datetime.now(ZoneInfo(dcfg["timezone"]))
    last_daily = ctx.db.get_meta("last_daily_date")
    if last_daily and last_daily != now_l.date().isoformat() and now_l.hour >= daily_hour and now_l.hour < 22:
        sched.add_job(do_daily, DateTrigger(run_date=datetime.now(timezone.utc) + timedelta(seconds=90)), id="daily_catchup")
        log.info("Сегодняшняя рассылка не уходила — наверстаю через 90 секунд")
    nxt = sched.get_job("daily").next_run_time
    log.info("Бот запущен. Whitelist: %d пользователей, чатов для дайджеста: %d. Следующая рассылка: %s",
             len(env.allowed_ids), len(env.chat_ids), nxt)
    await startup_check()
    try:
        if nxt:
            await notify_admin(f"🟢 Радар запущен. Рассылка раз в день: <b>{nxt:%d.%m %H:%M}</b> ({dcfg['timezone']}). "
                               f"Фоновый сбор: {', '.join(f'{h:02d}:00' for h in hours_list) if hours_list else 'каждые ' + str(dcfg['every_hours']) + ' ч'}.")
        await dp.start_polling(ctx.bot)
    finally:
        sched.shutdown(wait=False)
        await ctx.bot.session.close()
