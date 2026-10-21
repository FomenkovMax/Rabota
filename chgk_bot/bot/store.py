"""Выбор хранилища: общая БД (DATABASE_URL задан) или старые файлы MVP (questions.json + stats.sqlite)."""
import os
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent


def open_storage(data_dir: Path):
    """Возвращает (банк вопросов, статистика). Интерфейс у обоих вариантов одинаковый."""
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        from core.db import make_session_factory
        from core.repo import QuestionRepo, StatsRepo
        f = make_session_factory(url)
        return QuestionRepo(f), StatsRepo(f)
    from .storage import QuestionBank, Stats
    return QuestionBank(data_dir / "questions.json", seed=PKG_DIR / "seed_questions.json"), Stats(data_dir / "stats.sqlite")
