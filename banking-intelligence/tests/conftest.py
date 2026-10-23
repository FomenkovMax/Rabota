import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine

from bankintel.config import get_settings
from bankintel.db import models  # noqa: F401
from bankintel.db.base import Base
from bankintel.db.session import make_session_factory
from bankintel.registry.loader import load_config, sync_registry


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield make_session_factory(engine)
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded(session_factory):
    cfg = load_config(get_settings().config_dir)
    async with session_factory() as s:
        await sync_registry(s, cfg)
    return session_factory
