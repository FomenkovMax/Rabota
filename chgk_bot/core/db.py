"""Подключение к БД. Боту и бэкенду нужен один и тот же слой, поэтому он здесь, в общем пакете core.

Работаем синхронным SQLAlchemy 2.0: для команды из 5–10 человек запросы занимают миллисекунды,
а код проще (без async-сессий). FastAPI запускает такие вызовы в пуле потоков."""
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        # тесты и локальный запуск без Postgres: одна общая подключённая база в памяти/файле
        kwargs = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url or url == "sqlite://":
            kwargs["poolclass"] = StaticPool
        return create_engine(url, **kwargs)
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)


def make_session_factory(url: str) -> sessionmaker[Session]:
    return sessionmaker(make_engine(url), expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]):
    """with session_scope(factory) as s: ... — коммит при успехе, откат при ошибке."""
    s = factory()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
