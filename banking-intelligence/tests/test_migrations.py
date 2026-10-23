import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from bankintel.db import models  # noqa: F401
from bankintel.db.base import Base


def _cfg(url: str) -> Config:
    cfg = Config("alembic.ini")
    cfg.cmd_opts = type("O", (), {"x": [f"url={url}"]})()
    return cfg


def _roundtrip(async_url: str, sync_url: str):
    cfg = _cfg(async_url)
    command.upgrade(cfg, "head")
    tables = set(inspect(create_engine(sync_url)).get_table_names())
    assert set(Base.metadata.tables) <= tables
    command.check(cfg)  # модели и миграции не расходятся
    command.downgrade(cfg, "base")
    assert not (set(Base.metadata.tables) & set(inspect(create_engine(sync_url)).get_table_names()))


def test_migrations_sqlite(tmp_path):
    f = tmp_path / "m.db"
    _roundtrip(f"sqlite+aiosqlite:///{f}", f"sqlite:///{f}")


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URL"), reason="нужен TEST_POSTGRES_URL (postgresql://...)")
def test_migrations_postgres():
    url = os.environ["TEST_POSTGRES_URL"]
    _roundtrip(url.replace("postgresql://", "postgresql+asyncpg://"), url.replace("postgresql://", "postgresql+psycopg2://"))
