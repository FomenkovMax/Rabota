import random
from collections import Counter

import pytest

from core import teamgame as T
from core import wheel

QS = [f"q{i}" for i in range(20)]


def test_wheel_never_repeats_and_ends():
    rng = random.Random(1)
    played = set()
    for _ in range(13):
        s = wheel.pick_sector(played, rng=rng)
        assert s is not None and s not in played
        played.add(s)
    assert wheel.pick_sector(played, rng=rng) is None and wheel.spin(played) is None


def test_wheel_next_free_clockwise():
    class R(random.Random):
        def randrange(self, n): return 5
    assert wheel.pick_sector({5, 6, 7}, 13, R()) == 8
    assert wheel.pick_sector({5, 6, 7, 8, 9, 10, 11, 12, 0, 1, 2, 3}, 13, R()) == 4   # круг замкнулся


def test_wheel_uniform_over_free():
    rng = random.Random(7)
    played = {0, 1, 2}
    c = Counter(wheel.pick_sector(played, rng=rng) for _ in range(20000))
    assert set(c) == set(range(3, 13))
    # сектор 3 получает и свою долю, и долю 0..2 (идём по часовой) — остальные поровну; проверяем, что нет «мёртвых»
    assert all(v > 800 for v in c.values())


def play(g, results, now=0.0):
    for ok in results:
        T.start_round(g, now) if g["phase"] == "idle" else None
        assert g["phase"] == "think"
        T.submit(g, 1, "ответ", now)
        T.set_verdict(g, {"level": "correct" if ok else "wrong", "score": 1.0 if ok else 0.0, "comment": "", "source": "llm", "disputed": False}, now)
        T.advance(g, 1, now)


def test_sport_scoring_and_finish():
    g = T.new_game("sport", QS, 1, 0, tours=2, per_tour=3)
    assert g["total"] == 6
    play(g, [True, False, True, True, False, False])
    assert g["status"] == "finished" and g["score"] == 3.0 and len(g["log"]) == 6


def test_timers_idempotent_and_captain_only():
    g = T.new_game("sport", QS, 1, 0)
    T.start_round(g, 0)
    assert T.to_answer(g, 60) and not T.to_answer(g, 61)
    with pytest.raises(T.GameError):
        T.submit(g, 2, "x", 61)
    assert T.timeout_answer(g, 80) and not T.timeout_answer(g, 81)
    assert g["verdict"]["source"] == "timeout"
    with pytest.raises(T.GameError):
        T.override(g, 2, True)
    T.override(g, 1, True)
    T.advance(g, 1, 90)
    assert g["score"] == 1.0                        # override учтён при фиксации


def test_wheel_game_to_six_points():
    g = T.new_game("wheel", QS, 1, 0, rng=random.Random(5))
    rng = random.Random(3)
    T.start_round(g, 0, rng)
    seen = set()
    while g["status"] == "active":
        if g["current"]["sub"] == 0:                 # новый сектор (вопросы блица идут в том же секторе)
            assert g["current"]["sector"] not in seen
            seen.add(g["current"]["sector"])
        if g["phase"] == "pick":
            T.pick_answerer(g, 1, 1, 0)
        T.submit(g, 1, "а", 0)
        T.set_verdict(g, {"level": "correct", "score": 1.0, "comment": "", "source": "exact", "disputed": False}, 0)
        T.advance(g, 1, 0, rng)
    assert g["experts"] == 6 and g["viewers"] == 0


def test_commit_only_once():
    g = T.new_game("sport", QS, 1, 0)
    T.start_round(g, 0)
    T.submit(g, 1, "а", 0)
    T.set_verdict(g, {"level": "correct", "score": 1.0, "comment": "", "source": "exact", "disputed": False}, 0)
    T.commit_round(g); T.commit_round(g)
    assert g["score"] == 1.0


def ok(g, user=1, level="correct"):
    T.submit(g, user, "ответ", 0)
    T.set_verdict(g, {"level": level, "score": 1.0 if level == "correct" else 0.0, "comment": "", "source": "exact", "disputed": False}, 0)


def wheel_at(kind):
    """Волчок, где стрелка выпала на нужный особый сектор."""
    g = T.new_game("wheel", QS, 1, 0, rng=random.Random(1))
    sector = g["kinds"].index(kind)
    class R(random.Random):
        def randrange(self, n): return sector
        def randint(self, a, b): return a
        def uniform(self, a, b): return 0.0
    T.start_round(g, 0, R())
    assert g["current"]["kind"] == kind and g["current"]["sector"] == sector
    return g


def test_specials_assigned_once_and_use_extra_questions():
    g = T.new_game("wheel", QS, 1, 0, rng=random.Random(9))
    assert g["kinds"].count("blitz") == 1 and g["kinds"].count("superblitz") == 1 and len(g["kinds"]) == 13
    for sector, qs in g["blitz_q"].items():
        assert len(qs) == 3 and qs[0] == g["questions"][int(sector)]
        assert len(set(qs)) == 3
    used = [q for qs in g["blitz_q"].values() for q in qs[1:]]
    assert not set(used) & set(g["questions"])          # дополнительные вопросы не пересекаются с секторами
    few = T.new_game("wheel", QS[:13], 1, 0)            # вопросов мало — обычный волчок без особых секторов
    assert set(few["kinds"]) == {"normal"}


def test_blitz_all_three_correct_gives_experts_point():
    g = wheel_at("blitz")
    assert g["phase"] == "think" and g["deadline"] == T.BLITZ_THINK + T.SPIN_DELAY
    first = g["current"]["qid"]
    for i in range(3):
        assert g["current"]["sub"] == i
        ok(g)
        T.advance(g, 1, 100 + i)
        if i < 2:
            assert g["current"]["kind"] == "blitz" and g["experts"] == 0 and g["current"]["qid"] != first
            assert g["deadline"] == 100 + i + T.BLITZ_THINK      # без повторного вращения стрелки
    assert g["experts"] == 1 and g["viewers"] == 0
    assert g["current"]["kind"] != "blitz" or g["current"]["sub"] == 0     # перешли к следующему сектору


def test_blitz_first_error_gives_viewers_point_and_ends_round():
    g = wheel_at("blitz")
    ok(g)
    T.advance(g, 1, 1)
    ok(g, level="close")                      # «почти» в волчке — не взят
    T.advance(g, 1, 2)
    assert g["viewers"] == 1 and g["experts"] == 0
    assert g["current"]["sub"] == 0            # блиц закончен, крутим дальше
    assert len(g["log"]) == 2


def test_superblitz_only_chosen_player_answers():
    g = wheel_at("superblitz")
    assert g["phase"] == "pick" and g["deadline"] == 0.0
    with pytest.raises(T.GameError):
        T.submit(g, 1, "x", 0)                # пока игрок не выбран, ответить нельзя
    with pytest.raises(T.GameError):
        T.pick_answerer(g, 2, 2, 0)           # выбирает только капитан
    T.pick_answerer(g, 1, 7, 50)
    assert g["phase"] == "think" and g["deadline"] == 50 + T.BLITZ_THINK
    with pytest.raises(T.GameError, match="выбранный"):
        T.submit(g, 1, "капитан не помогает", 51)
    for i in range(3):
        ok(g, user=7)
        T.advance(g, 1, 60 + i)              # «дальше» по-прежнему жмёт капитан
    assert g["experts"] == 1
