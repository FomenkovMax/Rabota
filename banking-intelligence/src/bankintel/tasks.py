"""Celery: периодический цикл мониторинга.

Запуск:
  celery -A bankintel.tasks worker -l info --concurrency 1
  celery -A bankintel.tasks beat -l info --schedule /tmp/celerybeat-schedule
"""

import asyncio

from celery import Celery
from celery.signals import setup_logging

from bankintel.config import get_settings
from bankintel.cycle import redis_lock, run_cycle, telegram_notifier

settings = get_settings()


@setup_logging.connect  # собственный формат Celery заменяем на общий (с маскировкой секретов)
def _configure_logging(**_):
    from bankintel.logging_setup import configure_logging

    configure_logging(settings.log_level, settings.log_json)


app = Celery("bankintel", broker=settings.redis_url)
app.conf.update(
    timezone="UTC", task_acks_late=True, worker_prefetch_multiplier=1, broker_connection_retry_on_startup=True,
    beat_schedule={"monitor-cycle": {"task": "bankintel.monitor_cycle", "schedule": settings.monitor_interval_hours * 3600,
                                    "options": {"expires": settings.monitor_interval_hours * 3600 * 0.9}}},  # просроченные не копятся
)


async def _cycle() -> dict:
    from bankintel.db.session import make_engine, make_session_factory
    from bankintel.sources.fetcher import build_fetcher

    s = get_settings()
    engine, fetcher = make_engine(s.database_url), build_fetcher(s)
    try:
        return await run_cycle(s, make_session_factory(engine), fetcher, notifier=telegram_notifier(s))
    finally:
        await fetcher.aclose()
        await engine.dispose()


# лимиты работают в prefork-пуле (docker); защита от зависшего цикла, держащего замок
@app.task(name="bankintel.monitor_cycle", soft_time_limit=1500, time_limit=1800)
def monitor_cycle() -> dict:
    with redis_lock(get_settings().redis_url) as got:
        if not got:
            return {"skipped": "предыдущий цикл ещё выполняется"}
        return asyncio.run(_cycle())
