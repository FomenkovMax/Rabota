import datetime as dt

from core import seasons as S
from core.brand import load_brand
from core.db import make_session_factory
from core.models import Attempt, Award, Base, Game, User
from core.repo import QuestionRepo

BRAND = load_brand("config/brand.json")
MSK = dt.timezone(dt.timedelta(hours=3))


def ts(y, m, d, h=12):
    return dt.datetime(y, m, d, h, tzinfo=MSK).timestamp()


def setup():
    f = make_session_factory("sqlite://")
    Base.metadata.create_all(f.kw["bind"])
    QuestionRepo(f).add([{"text": "В?", "answer": "а", "explanation": "б"}])
    return f


def add(f, uid, when, scores):
    with f() as s:
        if not s.get(User, uid):
            s.add(User(tg_id=uid, name=f"u{uid}"))
        for i, sc in enumerate(scores):
            s.add(Attempt(actor_id=uid, question_id="q", score=sc, mode="solo", ts=when + i))
        s.commit()


def test_season_bounds_and_key():
    assert S.season_key(ts(2026, 3, 31, 23)) == "2026-03"
    assert S.season_key(ts(2026, 4, 1, 0)) == "2026-04"        # полночь по Москве — уже апрель
    a, b = S.season_bounds("2026-12")
    assert dt.datetime.fromtimestamp(b, MSK).strftime("%Y-%m-%d") == "2027-01-01"


def test_leagues():
    names = [S.league_of(p, BRAND)["id"] for p in (0, 29.5, 30, 79, 80, 500)]
    assert names == ["bronze", "bronze", "silver", "silver", "gold", "gold"]


def test_standings_order_and_month_isolation():
    f = setup()
    add(f, 1, ts(2026, 5, 3), [1, 1, 1])
    add(f, 2, ts(2026, 5, 4), [1, 0.5])
    add(f, 2, ts(2026, 6, 4), [1] * 50)            # другой месяц не мешает
    t = S.standings(f, "2026-05")
    assert [r["user_id"] for r in t] == [1, 2] and t[0]["rank"] == 1 and t[1]["points"] == 1.5


def test_awards_idempotent_and_diamond():
    f = setup()
    add(f, 1, ts(2026, 5, 3), [1] * 50 + [0] * 5)            # 55 вопросов — на бриллиантовую мало
    add(f, 2, ts(2026, 5, 4), [1] * 65 + [0] * 5)            # 70 вопросов, точность ≈0.93
    now = ts(2026, 6, 2)
    given = S.finalize_seasons(f, BRAND, now)
    assert sorted(a.kind for a in given) == ["diamond_owl", "owl"] and all(a.user_id == 2 for a in given)
    assert S.finalize_seasons(f, BRAND, now) == []             # повторно ничего
    with f() as s:
        assert s.query(Award).count() == 2


def test_current_month_not_awarded():
    f = setup()
    add(f, 1, ts(2026, 6, 1), [1] * 5)
    assert S.finalize_seasons(f, BRAND, ts(2026, 6, 20)) == []


def test_achievements_once():
    f = setup()
    add(f, 1, ts(2026, 6, 1), [1] * 6 + [0])
    assert S.check_achievements(f, 1, BRAND) == ["first", "streak5"]
    assert S.check_achievements(f, 1, BRAND) == []
    add(f, 1, ts(2026, 6, 2), [1] * 10)
    assert S.check_achievements(f, 1, BRAND) == ["streak10"]


def test_captain_win_achievement():
    f = setup()
    with f() as s:
        s.add(Game(id="g", team_id=-1, mode="wheel", status="finished", state={"captain_id": 9, "experts": 6, "viewers": 3}))
        s.commit()
    assert S.check_achievements(f, 9, BRAND) == ["captain_win"]


def test_overview_progress():
    f = setup()
    add(f, 1, ts(2026, 6, 1), [1] * 35)
    o = S.season_overview(f, BRAND, 1, now=ts(2026, 6, 10))
    assert o["me"]["league"]["id"] == "silver" and o["me"]["next_league"]["id"] == "gold" and o["me"]["to_next"] == 45
    assert o["days_left"] == 20 and o["me"]["rank"] == 1
