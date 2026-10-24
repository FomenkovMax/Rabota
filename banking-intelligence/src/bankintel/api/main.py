from datetime import UTC, datetime

from fastapi import FastAPI
from sqlalchemy import func, select, text

from bankintel import __version__
from bankintel.config import get_settings
from bankintel.db.models import Bank, CollectionRun, Source
from bankintel.db.session import make_engine

app = FastAPI(title="Banking Intelligence AI", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
async def health() -> dict:
    """Живость сервиса и доступность БД."""
    engine = make_engine(get_settings().database_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok", "db": "ok", "version": __version__}
    except Exception as exc:  # диагностика, а не маскировка; детали ошибки наружу не отдаём
        return {"status": "degraded", "db": f"error: {type(exc).__name__}", "version": __version__}
    finally:
        await engine.dispose()


@app.get("/health/data")
async def health_data() -> dict:
    """Свежесть данных: по каждому банку с подтверждёнными источниками — возраст последнего успешного сбора.
    Устаревшим считается сбор старше 2 интервалов мониторинга (по умолчанию 12 ч)."""
    settings = get_settings()
    limit_h = settings.monitor_interval_hours * 2
    engine = make_engine(settings.database_url)
    try:
        banks = []
        async with engine.connect() as conn:
            rows = (await conn.execute(
                select(Bank.slug, func.max(CollectionRun.started_at))
                .join(Source, (Source.bank_id == Bank.id) & (Source.status == "active"))
                .outerjoin(CollectionRun, (CollectionRun.bank_id == Bank.id) & CollectionRun.status.in_(("ok", "partial")))
                .group_by(Bank.slug).order_by(Bank.slug)
            )).all()
        now = datetime.now(UTC)
        for slug, last in rows:
            if last is None:
                banks.append({"bank": slug, "last_success": None, "age_hours": None, "stale": True})
                continue
            last = last if last.tzinfo else last.replace(tzinfo=UTC)
            age = (now - last).total_seconds() / 3600
            banks.append({"bank": slug, "last_success": last.isoformat(), "age_hours": round(age, 1), "stale": age > limit_h})
        stale = [b["bank"] for b in banks if b["stale"]]
        return {"status": "ok" if banks and not stale else "degraded", "stale_banks": stale, "max_age_hours": limit_h, "banks": banks}
    except Exception as exc:
        return {"status": "degraded", "error": type(exc).__name__}
    finally:
        await engine.dispose()
