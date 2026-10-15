import asyncio
import json
import sqlite3

from bot import game as G
from core import steps as S
from bot.storage import QuestionBank, Stats


def test_question_rates_use_first_attempt_only(tmp_path):
    st = Stats(tmp_path / "s.sqlite")
    st.record(1, "q", 0.0, "x")
    st.record(1, "q", 1.0, "y")      # повтор того же игрока не меняет «долю взявших»
    st.record(2, "q", 1.0, "z")
    st.record(3, "q", 0.5, "w")      # «почти» — не взял
    assert st.question_rates()["q"] == (3, 1)
    n, share = st.rate("q")
    assert n == 3 and abs(share - 1 / 3) < 1e-9
    assert st.rate("none") == (0, None)


def test_hidden_ids_need_enough_answers(tmp_path):
    st = Stats(tmp_path / "s.sqlite")
    for u in range(6):
        st.record(u, "easy", 1.0, "a")
        st.record(u, "hard", 0.0, "a")
        st.record(u, "ok", 1.0 if u < 3 else 0.0, "a")
    for u in range(3):
        st.record(u, "few", 1.0, "a")   # мало ответов — не скрываем
    assert st.hidden_ids(min_n=6) == {"easy", "hard"}


def test_old_database_is_migrated(tmp_path):
    p = tmp_path / "old.sqlite"
    db = sqlite3.connect(p)
    db.execute("CREATE TABLE results (user_id INTEGER, qid TEXT, score REAL, answer TEXT, ts REAL)")
    db.execute("INSERT INTO results VALUES (1,'q',1.0,'a',1.0)")
    db.commit(); db.close()
    st = Stats(p)
    st.record(-100, "q", 1.0, "a", mode="team")
    assert st.summary(1)["played"] == 1 and st.summary(-100)["correct"] == 1


def test_pick_and_choose_respect_exclude_and_seen(tmp_path):
    bank = QuestionBank(tmp_path / "q.json")
    bank.add([{"text": f"Вопрос {i}?", "answer": f"О{i}", "explanation": "e"} for i in range(6)])
    ids = [q["id"] for q in bank.items]
    q, fresh = bank.pick(set(), exclude={ids[0], ids[1]})
    assert q["id"] not in {ids[0], ids[1]} and fresh == 4
    got = bank.choose(4, seen={ids[2]}, exclude={ids[0]})
    assert len(got) == 4 and len({x["id"] for x in got}) == 4 and ids[0] not in {x["id"] for x in got}
    got = bank.choose(6, seen=set(ids[:5]), exclude=set())   # не хватает новых — добираем играные
    assert len(got) == 6


def test_steps_cache(tmp_path):
    bank = QuestionBank(tmp_path / "q.json")
    bank.add([{"text": "В?", "answer": "О", "explanation": "e"}])
    qid = bank.items[0]["id"]
    bank.set_steps(qid, {"steps": [{"clue": "а", "inference": "б", "how": "логика"}], "lesson": "в"})
    assert QuestionBank(tmp_path / "q.json").get(qid)["steps"]["lesson"] == "в"


class FakeLLM:
    def __init__(self, text):
        self.text, self.messages = text, self

    async def create(self, **kw):
        return type("R", (), {"content": [type("B", (), {"text": self.text})()]})()


def test_make_and_render_steps():
    reply = json.dumps({"steps": [{"clue": "забыли отдать приказы", "inference": "звонарям не сказали звонить", "how": "логика"},
                                  {"clue": "молчание пушек", "inference": "значит, это колокола", "how": "ассоциация"}],
                        "lesson": "Замена слова видна по контексту <b>"})
    q = {"text": "…", "answer": "колокол", "explanation": "e"}
    data = asyncio.run(S.make_steps(FakeLLM(reply), "m", q))
    assert len(data["steps"]) == 2
    text = S.render_steps(q, data)
    assert "1️⃣" in text and "2️⃣" in text and "&lt;b&gt;" in text and "колокол" in text   # HTML экранируется
    assert asyncio.run(S.make_steps(FakeLLM("не json"), "m", q)) is None
    assert "Шаги сейчас недоступны" in S.render_steps(q, None)


def test_team_game_scoring_and_tours():
    g = G.TeamGame(chat_id=-1, captain_id=1, captain_name="К", queue=[{"id": str(i)} for i in range(5)], per_tour=2)
    assert (g.total, g.tours, g.tour, g.number_in_tour) == (5, 3, 1, 1)
    g.results[0], g.results[1], g.results[2] = True, False, True
    g.idx = 1
    assert g.is_last_in_tour() and not g.is_last()
    assert g.tour_score(1) == (1, 2) and g.tour_score(2) == (1, 2) and g.tour_score(3) == (0, 1)
    g.idx = 4
    assert g.is_last() and g.is_last_in_tour() and (g.tour, g.number_in_tour) == (3, 1)
    text = G.final_summary(g)
    assert "Тур 1" in text and "2 из 3" in text
