import json
from datetime import datetime, timedelta, timezone

import pytest

from radar.bot.auth import command_of, is_allowed
from radar.bot.sender import recipients
from radar.db import DB
from radar.llm.client import LLMClient, LLMResult
from radar.report.digest import TG_LIMIT, build_digest
from radar.sources.base import Post


def test_whitelist():
    allowed = {1, 2}
    assert is_allowed(1, allowed) and not is_allowed(99, allowed) and not is_allowed(None, allowed)
    assert command_of("/myid@radar_bot x") == "/myid"


def test_recipients_group_plus_dm_with_mute():
    assert recipients([-100], {1, 2, 3}, muted={2}) == [-100, 1, 3]
    assert recipients([-100, 1], {1}, muted=set()) == [-100, 1]   # без дублей


def _ev(i, score=4, cat=3):
    return {"category": cat, "title": f"Событие <{i}>", "summary": "Суть & детали", "relevance_score": score,
            "organizations": [{"name": "ООО Ромашка", "inn_if_in_text": None}], "persons": [],
            "source_urls": [f"https://t.me/a/{i}"], "business_opportunity": "зарплатный проект"}


def test_digest_empty():
    now = datetime.now(timezone.utc)
    assert "Новых значимых событий нет" in build_digest([], now - timedelta(hours=4), now, 0)


def test_digest_escapes_limits_and_footer():
    now = datetime.now(timezone.utc)
    txt = build_digest([_ev(i) for i in range(60)], now - timedelta(hours=4), now, 3, max_events=60)
    assert len(txt) <= TG_LIMIT
    assert "&lt;" in txt and "ИНН н/д" in txt           # экранирование и «н/д» вместо выдумки
    assert "не удалось прочитать: 3" in txt and "ещё" in txt


class FakeLLM(LLMClient):
    async def complete(self, model, system, user, max_tokens=1500):
        if "фильтр" in system:   # дешёвый фильтр: всё релевантно
            n = user.count("\n\n") + 1
            return LLMResult(json.dumps({"results": [{"i": i, "relevant": True} for i in range(n)]}), 100, 20)
        return LLMResult(json.dumps({"category": 1, "title": "Открытие", "summary": "Открылся филиал",
                                     "organizations": [{"name": "ООО Ромашка", "inn_if_in_text": "1234567890"}],
                                     "relevance_score": 5, "amounts": ["99 млн"]}), 300, 80)


class FakeSource:
    async def fetch(self, ch, since):
        return [Post(ch, 1, f"https://t.me/{ch}/1", "Открылся новый филиал ООО Ромашка в Луганске, " * 2,
                     datetime.now(timezone.utc))]

    async def polite_pause(self): pass
    async def aclose(self): pass


async def test_full_pipeline_with_fakes(tmp_path, monkeypatch):
    from radar import pipeline
    monkeypatch.setattr(pipeline, "make_client", lambda env: FakeLLM())
    monkeypatch.setattr(pipeline, "load_channels", lambda: [{"username": "a"}, {"username": "b"}])
    db = DB(tmp_path / "t.db")
    res = await pipeline.run_once(db, hours=24, source=FakeSource())
    assert res.posts_new == 2 and len(res.events) == 1            # два канала = один инфоповод
    ev = res.events[0]
    assert len(ev["source_urls"]) == 2                             # оба источника в событии
    assert ev["organizations"][0]["inn_if_in_text"] is None        # выдуманный ИНН обнулён
    assert ev["amounts"] == []                                     # выдуманная сумма обнулена
    assert db.stats()["events"] == 1 and db.last_success() is not None
    res2 = await pipeline.run_once(db, source=FakeSource())        # те же посты — уже известны
    assert res2.posts_new == 0


def _evs(scores):
    return [_ev(i, score=sc, cat=3 + (i % 2)) for i, sc in enumerate(scores)]


def test_digest_shows_only_3_plus_and_counts_dashboard_extra():
    now = datetime.now(timezone.utc)
    events = _evs([5, 4, 3, 2, 2, 1])          # 3 события ≥3⭐, ещё 2 — только для дашборда (2⭐), 1⭐ нигде
    txt = build_digest(events, now - timedelta(hours=4), now, 0, min_score=3, dash_min_score=2)
    assert "⭐5" in txt and "⭐3" in txt and "⭐2" not in txt and "⭐1" not in txt
    assert "Событий от 3⭐: 3" in txt
    assert "ещё 2" in txt and "дашборд" in txt   # 2⭐-события доступны в дашборде


def test_digest_only_two_star_events_points_to_dashboard():
    now = datetime.now(timezone.utc)
    txt = build_digest(_evs([2, 2]), now - timedelta(hours=4), now, 0, min_score=3, dash_min_score=2)
    assert "Новых значимых событий нет (от 3⭐)" in txt and "В дашборде ещё 2" in txt


def test_digest_shows_candidate_inns_for_needs_review():
    now = datetime.now(timezone.utc)
    e = _ev(1)
    e["enriched"] = {"status": "needs_review", "matched_org": "ООО Ромашка", "card": None,
                     "candidates": [{"name_full": "ООО Ромашка-1", "inn": "7707083893", "address": "Луганская Народная Респ, г Луганск"}]}
    txt = build_digest([e], now - timedelta(hours=4), now, 0)
    assert "требует проверки" in txt and "7707083893" in txt and "Варианты" in txt


def test_digest_hours_argument_parsing():
    """Окно в часах берётся из первого слова; «@Radar_Bank_Bot» после числа не мешает."""
    from radar.report.snapshot import parse_hours as parse
    assert parse("24 @Radar_Bank_Bot") == 24.0 and parse("6") == 6.0 and parse("1,5") == 1.5
    assert parse(None) is None and parse("@Radar_Bank_Bot") is None and parse("abc") is None
    assert parse("9999") == 168.0                         # не больше недели
    assert parse(None, default=24.0) == 24.0
