from fastapi import FastAPI
from sqlalchemy import text

from bankintel import __version__
from bankintel.config import get_settings
from bankintel.db.session import make_engine

app = FastAPI(title="Banking Intelligence AI", version=__version__)


@app.get("/health")
async def health() -> dict:
    """Живость сервиса и доступность БД."""
    engine = make_engine(get_settings().database_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok", "db": "ok", "version": __version__}
    except Exception as exc:  # диагностика, а не маскировка
        return {"status": "degraded", "db": f"error: {type(exc).__name__}", "version": __version__}
    finally:
        await engine.dispose()
