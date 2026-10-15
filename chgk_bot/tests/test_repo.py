"""Репозитории над БД (SQLite в тестах, PostgreSQL на сервере) и миграции Alembic."""
import os
import subprocess
import sys

import pytest
from sqlalchemy import inspect

from core.db import make_engine, make_session_factory
from core.models import Base
from core.repo import QuestionRepo, StatsRepo, UserRepo, make_id


@pytest.fixture
def repos(tmp_path):
    url = f"sqlite:///{tmp_path / 't.db'}"
    f = make_session_factory(url)
    Base.metadata.create_all(f.kw["bind"])
    return QuestionRepo(f), StatsRepo(f), UserRepo(f)


def qs(n=6):
    return [{"text": f"Вопрос {i}?", "answer": f"О{i}", "explanation": f"Разбор{i}", "author": "А", "tags": ["тема"]}
            for i in range(n)]


def test_alembic_upgrade_matches_models(tmp_path):
    """Миграция должна создавать ровно те таблицы и колонки, что описаны в моделях."""
    url = f"sqlite:///{tmp_path / 'mig.db'}"
    env = dict(os.environ, DATABASE_URL=url)
    root = os.path.dirname(os.path.dirname(__file__))
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    insp = inspect(make_engine(url))
    for name, table in Base.metadata.tables.items():
        assert {c["name"] for c in insp.get_columns(name)} == {c.name for c in table.columns}, name
    r = subprocess.run([sys.executable, "-m", "alembic", "downgrade", "base"], cwd=root, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_question_roundtrip_and_ids(repos):
    bank, _, _ = repos
    assert bank.add(qs(3)) == 3 and bank.count() == 3
    assert bank.add(qs(3)) == 0                                    # дубли пропускаются
    q = bank.get(make_id("Вопрос 1?"))
    assert q["answer"] == "О1" and q["explanation"] == "Разбор1" and q["tags"] == ["тема"] and q["pack_title"] == ""
    assert bank.add([{"text": "без ответа"}]) == 0                 # неполные пропускаются


def test_update_keeps_steps_cache_and_remove(repos):
    bank, _, _ = repos
    bank.add(qs(2))
    qid = make_id("Вопрос 0?")
    bank.set_steps(qid, {"steps": [], "lesson": "x"})
    changed = dict(qs(1)[0], explanation="Новый разбор")
    assert bank.add([changed], update=True) == 0
    q = bank.get(qid)
    assert q["explanation"] == "Новый разбор" and q["steps"]["lesson"] == "x"
    assert bank.remove_answers(["о0"]) == 1 and bank.count() == 1


def test_pick_and_choose(repos):
    bank, _, _ = repos
    bank.add(qs(6))
    ids = sorted(make_id(f"Вопрос {i}?") for i in range(6))
    q, fresh = bank.pick(set(), exclude={ids[0], ids[1]})
    assert q["id"] not in {ids[0], ids[1]} and fresh == 4
    got = bank.choose(4, seen={ids[2]}, exclude={ids[0]})
    assert len(got) == 4 and len({x["id"] for x in got}) == 4 and ids[0] not in {x["id"] for x in got}
    assert len(bank.choose(6, seen=set(ids[:5]))) == 6             # не хватает новых — добираем играные
    q, fresh = bank.pick(set(ids))
    assert q is not None and fresh == 0


def test_stats_summary_rates_hidden_and_seen(repos):
    bank, stats, _ = repos
    stats.record(1, "q", 0.0, "x")
    stats.record(1, "q", 1.0, "y")      # повтор того же игрока не меняет «долю взявших»
    stats.record(2, "q", 1.0, "z")
    stats.record(3, "q", 0.5, "w")      # «почти» — не взял
    assert stats.question_rates()["q"] == (3, 1)
    n, share = stats.rate("q")
    assert n == 3 and abs(share - 1 / 3) < 1e-9 and stats.rate("none") == (0, None)
    assert stats.summary(1) == {"played": 2, "points": 1.0, "correct": 1, "close": 0}
    assert stats.seen(3) == {"q"} and stats.summary(99)["played"] == 0
    for u in range(10, 16):
        stats.record(u, "easy", 1.0, "a")
        stats.record(u, "hard", 0.0, "a")
        stats.record(u, "ok", 1.0 if u < 13 else 0.0, "a")
    assert stats.hidden_ids(min_n=6) == {"easy", "hard"}


def test_user_touch_creates_then_updates(repos):
    _, _, users = repos
    users.touch(5, "Аня", "anya")
    users.touch(5, "Аня К.", "anya")
    from core.models import User
    with users.f() as s:
        assert s.get(User, 5).name == "Аня К."
