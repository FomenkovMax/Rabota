import sqlite3

import pytest

from radar.config import load_channels
from radar.daily import card_text, header_text, keyboard, pick_events
from radar.db import DB
from radar.report.feedback import calibration_text, feedback_report, parse_vote, vote_data
from datetime import datetime, timezone


def ev(title, score=4, cat=1):
    return {"category": cat, "title": title, "summary": "Суть", "relevance_score": score,
            "organizations": [], "source_urls": ["https://t.me/a/1"], "channels": ["a"], "post_keys": []}


def test_new_events_are_unsent_and_mark_sent(tmp_path):
    db = DB(tmp_path / "t.db")
    rid = db.start_run()
    a, b = db.save_event(rid, ev("А")), db.save_event(rid, ev("Б"))
    assert [e["id"] for e in db.unsent_events()] == [a, b]
    db.mark_sent([a])
    assert [e["id"] for e in db.unsent_events()] == [b]


def test_migration_marks_old_events_sent(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)   # база старой версии: без sent_at
    con.executescript("""CREATE TABLE runs(id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT, finished_at TEXT, status TEXT,
        posts_new INTEGER, events_n INTEGER, tokens_in INTEGER, tokens_out INTEGER, cost_usd REAL, channel_errors TEXT);
        CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, created_at TEXT, category INTEGER,
        score INTEGER, title TEXT, data TEXT);
        INSERT INTO events(run_id, created_at, category, score, title, data) VALUES (1,'2026-01-01T00:00:00+00:00',1,4,'old','{}');""")
    con.commit(); con.close()
    db = DB(path)
    assert db.unsent_events() == []      # старая лента не должна хлынуть в первую рассылку


def test_votes_one_per_user_and_revote(tmp_path):
    db = DB(tmp_path / "t.db")
    eid = db.save_event(db.start_run(), ev("А"))
    db.set_vote(eid, 1, 5)
    db.set_vote(eid, 2, 3)
    assert db.vote_stats(eid) == (4.0, 2)
    db.set_vote(eid, 2, 1)               # переголосовал — голос заменяется, а не добавляется
    assert db.vote_stats(eid) == (3.0, 2)
    with pytest.raises(ValueError):
        db.set_vote(eid, 1, 6)
    assert db.feedback_rows()[0]["n"] == 2


def test_spent_since_sums_runs(tmp_path):
    db = DB(tmp_path / "t.db")
    for spent in (100, 250):
        rid = db.start_run()
        db.finish_run(rid, "ok", tokens_spent=spent, tokens_left=1000)
    assert db.spent_since("2000-01-01") == 350
    assert DB(tmp_path / "e.db").spent_since("2000-01-01") is None


def test_vote_callback_parsing():
    assert parse_vote(vote_data(7, 4)) == (7, 4)
    for bad in ("v:7:9", "v:x:1", "x:7:1", "", None, "v:7"):
        assert parse_vote(bad) is None


def test_pick_events_threshold_order_and_cap():
    evs = [{**ev("a", 2), "id": 1}, {**ev("b", 5), "id": 2}, {**ev("c", 3), "id": 3}, {**ev("d", 4), "id": 4}]
    cards, rest = pick_events(evs, 3, 2)
    assert [e["id"] for e in cards] == [2, 4]      # лучшие первыми, не больше max_cards
    assert {e["id"] for e in rest} == {1, 3}


def test_card_has_five_buttons_and_mine_marked():
    kb = keyboard(9, mine=4).inline_keyboard[0]
    assert [b.text for b in kb] == ["1", "2", "3", "[4]", "5"]
    assert kb[0].callback_data == "v:9:1"
    assert "средняя 4.5 (2 гол.)" in card_text({**ev("А", 4), "id": 9}, 4.5, 2, None)


def test_header_empty_and_filled():
    now = datetime.now(timezone.utc)
    assert "нет" in header_text([], 0, now, now, "Europe/Moscow", 0, "", 3)
    h = header_text([ev("А")], 5, now, now, "Europe/Moscow", 2, "🪙 Токенов", 3)
    assert "оцени полезность" in h and "Всего за период: 5" in h and "🪙" in h


def rows(n):
    return [{"id": i, "category": 1, "llm": 4, "title": f"Новость {i}", "avg": 5.0 if i % 2 else 1.0, "n": 3, "channels": []}
            for i in range(n)]


def test_calibration_needs_enough_data_then_gives_examples():
    assert calibration_text(rows(3)) == ""
    t = calibration_text(rows(8))
    assert "ПОЛЕЗНО" in t and "БЕСПОЛЕЗНО" in t


def test_feedback_report_shows_bias():
    out = feedback_report(rows(6))
    assert "⭐4" in out and "Перекос" in out
    assert "Оценок пока нет" in feedback_report([])


def test_admrov_removed():
    assert "admrov" not in {c["username"] for c in load_channels()}
