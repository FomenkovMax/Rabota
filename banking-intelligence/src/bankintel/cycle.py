"""Цикл мониторинга: сбор -> страницы продуктов -> обнаружение изменений -> уведомления."""

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from datetime import UTC, datetime
from html import escape

from sqlalchemy import select

from bankintel.collector import collect_all
from bankintel.db.models import Bank
from bankintel.details import collect_details
from bankintel.monitor import recent_changes

log = logging.getLogger("bankintel.cycle")
LOCK_KEY = "bankintel:monitor:lock"
NOTIFY_MIN_SEVERITY = "conditions"  # чисто текстовые правки (info) не рассылаем
_RELEASE = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"


@contextmanager
def redis_lock(redis_url: str, ttl_s: int = 3600):
    """Не даёт двум циклам идти одновременно. Отдаёт True, если замок получен.
    Если Redis недоступен — предупреждаем и продолжаем без замка (разовый запуск из консоли)."""
    import redis

    client, token = None, uuid.uuid4().hex
    try:
        client = redis.Redis.from_url(redis_url, socket_connect_timeout=3)
        got = bool(client.set(LOCK_KEY, token, nx=True, ex=ttl_s))
    except redis.RedisError as exc:
        log.warning("Redis недоступен (%s) — цикл запускается без межпроцессного замка", type(exc).__name__)
        yield True
        return
    try:
        yield got
    finally:
        if got:
            try:
                client.eval(_RELEASE, 1, LOCK_KEY, token)
            except redis.RedisError:
                pass


async def run_cycle(
    settings, session_factory, fetcher, *, notifier: Callable[[list[dict]], Awaitable[None]] | None = None, with_details: bool = True
) -> dict:
    started = datetime.now(UTC)
    t0 = time.monotonic()
    log.info("цикл мониторинга: старт")
    summary: dict = {"banks": {}, "events": 0, "notified": False}
    async with session_factory() as session:
        for bank, run in await collect_all(session, fetcher, settings.raw_storage_dir):
            prev = summary["banks"].get(bank.slug)
            summary["banks"][bank.slug] = run.status if prev in (None, "failed") else prev
        if with_details:
            for bank_id, slug, adapter in [(b.id, b.slug, b.adapter) for b in (await session.scalars(select(Bank).order_by(Bank.id))).all()]:
                if adapter == "generic":
                    continue
                try:
                    run = await collect_details(session, await session.get(Bank, bank_id), fetcher, settings.raw_storage_dir)
                    summary["banks"][f"{slug}:details"] = run.status
                except Exception:
                    log.exception("Сбой сбора страниц продуктов: %s", slug)
                    await session.rollback()
                    summary["banks"][f"{slug}:details"] = "failed"
        events = await recent_changes(session, started, min_severity=NOTIFY_MIN_SEVERITY)
        summary["events"] = len(await recent_changes(session, started))
    if events and notifier is not None:
        try:
            await notifier(events)
            summary["notified"] = True
        except Exception:  # сбой рассылки не должен ронять цикл мониторинга
            log.exception("Не удалось отправить уведомления об изменениях")
    summary["duration_s"] = round(time.monotonic() - t0, 1)
    log.info("цикл мониторинга: завершён за %.1f с, события=%s, статусы=%s", summary["duration_s"], summary["events"], summary["banks"])
    return summary


MARK = {"rate": "🔴", "conditions": "🟠", "info": "⚪"}


def format_events(events: list[dict], limit: int = 25) -> str:
    lines = [f"🔔 <b>Обнаружены изменения: {len(events)}</b>"]
    for e in events[:limit]:
        lines.append(f"{MARK.get(e['severity'], '')} {escape(e['text'])}")
    if len(events) > limit:
        lines.append(f"… и ещё {len(events) - limit}. Полный список: /changes")
    lines.append("\n⚠️ Данные с сайтов банков; доступность в ЛНР не подтверждена.")
    return "\n".join(lines)


def telegram_notifier(settings):
    """Рассылка только пользователям из ALLOWED_TELEGRAM_IDS и только если NOTIFY_CHANGES=true и задан BOT_TOKEN."""
    if not (settings.notify_changes and settings.bot_token and settings.allowed_telegram_ids):
        return None

    async def notify(events: list[dict]) -> None:
        from aiogram import Bot
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode

        text = format_events(events)[:4000]
        async with Bot(settings.bot_token.get_secret_value(), default=DefaultBotProperties(parse_mode=ParseMode.HTML)) as bot:
            for chat_id in settings.allowed_telegram_ids:
                try:
                    await bot.send_message(chat_id, text)
                except Exception:
                    log.exception("Не удалось отправить уведомление пользователю %s", chat_id)

    return notify
