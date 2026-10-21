import json
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend import auth
from backend.app import create_app
from backend.legacy import import_legacy
from backend.settings import Settings
from core.db import make_session_factory
from core.models import Attempt, Base, Question
from core.repo import QuestionRepo

BOT = "123456:TEST_TOKEN_for_tests_only"
QS = [
    {"text": f"Вопрос номер {i}?", "answer": f"ответ{i}", "explanation": "разбор", "accepted": []}
    for i in range(3)
]


def fields(uid=7, age=0, token=BOT):
    return {"auth_date": str(int(time.time()) - age), "query_id": "AAA",
            "user": json.dumps({"id": uid, "first_name": "Макс"}, ensure_ascii=False)}


def test_init_data_ok_forged_expired():
    data = auth.sign_init_data(fields(), BOT)
    assert auth.validate_init_data(data, BOT)["user"]["id"] == 7
    with pytest.raises(auth.AuthError):
        auth.validate_init_data(data.replace("%D0%9C", "%D0%9D", 1) if "%D0%9C" in data else data + "x", BOT)
    with pytest.raises(auth.AuthError):                      # чужой токен бота
        auth.validate_init_data(data, "999:OTHER")
    old = auth.sign_init_data(fields(age=10 * 86400), BOT)
    with pytest.raises(auth.AuthError, match="устарели"):
        auth.validate_init_data(old, BOT, max_age=86400)
    with pytest.raises(auth.AuthError):
        auth.validate_init_data("", BOT)


def test_token_roundtrip():
    t = auth.create_token(5, "A", "s" * 32, 60)
    assert auth.decode_token(t, "s" * 32) == {"id": 5, "name": "A"}
    with pytest.raises(auth.AuthError):
        auth.decode_token(t, "o" * 32)
    with pytest.raises(auth.AuthError):
        auth.decode_token(auth.create_token(5, "A", "s" * 32, -10), "s" * 32)


def make(tmp_path, **kw):
    s = Settings(database_url="sqlite://", bot_token=BOT, jwt_secret="x" * 32, think_seconds=60,
                 data_dir=tmp_path, **kw)
    f = make_session_factory("sqlite://")
    Base.metadata.create_all(f.kw["bind"])
    QuestionRepo(f).add([dict(q) for q in QS])
    return s, f, TestClient(create_app(s, factory=f))


def login(c, uid=7):
    r = c.post("/api/auth/telegram", json={"init_data": auth.sign_init_data(fields(uid), BOT)})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_auth_endpoint_rejects_forged(tmp_path):
    _, _, c = make(tmp_path)
    assert c.post("/api/auth/telegram", json={"init_data": "user=1&hash=00"}).status_code == 401
    assert c.get("/api/me").status_code == 401


def test_solo_flow_hides_answer_and_records(tmp_path):
    _, f, c = make(tmp_path)
    h = login(c)
    r = c.post("/api/solo/next", headers=h).json()
    assert "answer" not in json.dumps(r["question"]) and r["deadline_ms"] > r["server_now_ms"]
    qid = r["question"]["id"]
    ans = QuestionRepo(f).get(qid)["answer"]
    out = c.post("/api/solo/answer", headers=h, json={"round_id": r["round_id"], "answer": ans}).json()
    assert out["verdict"]["level"] == "correct" and out["reveal"]["answer"] == ans
    assert c.post("/api/solo/answer", headers=h, json={"round_id": r["round_id"], "answer": ans}).status_code == 409
    assert c.get("/api/me", headers=h).json()["stats"]["correct"] == 1


def test_timeout_and_skip_and_foreign_round(tmp_path):
    s, f, c = make(tmp_path)
    h = login(c)
    r = c.post("/api/solo/next", headers=h).json()
    from core.models import SoloRound
    with f() as ss:
        row = ss.get(SoloRound, r["round_id"])
        row.deadline_at = time.time() - 1000
        ss.commit()
    out = c.post("/api/solo/answer", headers=h, json={"round_id": r["round_id"], "answer": "что угодно"}).json()
    assert out["timeout"] and out["verdict"]["score"] == 0
    r2 = c.post("/api/solo/next", headers=h).json()
    other = login(c, uid=8)
    assert c.post("/api/solo/skip", headers=other, json={"round_id": r2["round_id"]}).status_code == 404
    assert c.post("/api/solo/skip", headers=h, json={"round_id": r2["round_id"]}).json()["reveal"]["answer"]


def test_steps_only_after_answer(tmp_path):
    _, _, c = make(tmp_path)
    h = login(c)
    r = c.post("/api/solo/next", headers=h).json()
    qid = r["question"]["id"]
    assert c.post(f"/api/questions/{qid}/steps", headers=h).status_code == 403
    c.post("/api/solo/skip", headers=h, json={"round_id": r["round_id"]})
    assert c.post(f"/api/questions/{qid}/steps", headers=h).status_code == 200


def test_access_restricted_by_ids(tmp_path):
    _, _, c = make(tmp_path, allowed_ids=frozenset({7}))
    assert c.post("/api/auth/telegram", json={"init_data": auth.sign_init_data(fields(7), BOT)}).status_code == 200
    assert c.post("/api/auth/telegram", json={"init_data": auth.sign_init_data(fields(9), BOT)}).status_code == 403


def test_legacy_import_idempotent(tmp_path):
    f = make_session_factory("sqlite://")
    Base.metadata.create_all(f.kw["bind"])
    (tmp_path / "questions.json").write_text(json.dumps(QS, ensure_ascii=False), encoding="utf-8")
    qid = QuestionRepo(make_session_factory("sqlite://")).__class__  # noqa: F841
    from core.repo import make_id
    db = sqlite3.connect(tmp_path / "stats.sqlite")
    db.execute("CREATE TABLE results (user_id INTEGER, qid TEXT, score REAL, answer TEXT, ts REAL, mode TEXT)")
    db.execute("INSERT INTO results VALUES (1, ?, 1, 'a', 1.0, 'solo')", (make_id(QS[0]["text"]),))
    db.execute("INSERT INTO results VALUES (1, 'нет-такого', 0, 'a', 2.0, 'solo')")
    db.commit(); db.close()
    rep = import_legacy(f, tmp_path)
    assert rep == {"questions_added": 3, "questions_skipped": 0, "attempts_added": 1, "attempts_skipped": 1}
    rep2 = import_legacy(f, tmp_path)
    assert rep2["questions_added"] == 0 and rep2["attempts_added"] == 0
    with f() as s:
        assert s.scalar(select(func.count()).select_from(Attempt)) == 1
        assert s.scalar(select(func.count()).select_from(Question)) == 3


def ws_token(c, uid):
    return login(c, uid)["Authorization"].split()[1]


def recv_state(ws):
    while True:
        m = ws.receive_json()
        if m["type"] == "state":
            return m


def test_ws_team_game_flow(tmp_path):
    s, f, c = make(tmp_path)
    t1, t2 = ws_token(c, 7), ws_token(c, 8)
    with c.websocket_connect(f"/api/ws?token={t1}") as a, c.websocket_connect(f"/api/ws?token={t2}") as b:
        recv_state(a)
        a.send_json({"type": "start", "mode": "sport", "tours": 1, "per_tour": 2})
        st = recv_state(a)
        while not st["game"]:
            st = recv_state(a)
        g = st["game"]
        assert g["phase"] == "think" and g["captain_id"] == 7 and g["total"] == 2
        assert "reveal" in g and g["reveal"] is None and "answer" not in json.dumps(g["question"])
        # не капитан не может отвечать
        b.send_json({"type": "answer", "text": "x"})
        while True:
            m = b.receive_json()
            if m["type"] == "error":
                assert "капитан" in m["message"]
                break
        qid = g["question"]["id"]
        right = QuestionRepo(f).get(qid)["answer"]
        a.send_json({"type": "answer", "text": right})
        st = recv_state(a)
        while st["game"]["phase"] != "review":
            st = recv_state(a)
        assert st["game"]["verdict"]["level"] == "correct" and st["game"]["reveal"]["answer"] == right
        a.send_json({"type": "next"})
        st = recv_state(a)
        while st["game"]["idx"] != 1:
            st = recv_state(a)
        assert st["game"]["score"] == 1.0
        a.send_json({"type": "stop"})
        st = recv_state(a)
        while st["game"]["status"] != "finished":
            st = recv_state(a)
        assert st["game"]["log"]


def test_ws_rejects_bad_token(tmp_path):
    _, _, c = make(tmp_path)
    with pytest.raises(Exception):
        with c.websocket_connect("/api/ws?token=bad"):
            pass


def test_stats_endpoints_and_card(tmp_path):
    from core.repo import StatsRepo
    s, f, c = make(tmp_path)
    h = login(c, 7)
    st = StatsRepo(f)
    ids = list(QuestionRepo(f).choose(3, set()))
    for i, q in enumerate(ids):
        st.record(7, q["id"], 1.0 if i != 1 else 0.0, "x", "solo", 4000)
    d = c.get("/api/stats/me", headers=h).json()
    assert d["played"] == 3 and d["correct"] == 2 and d["best_streak"] == 1 and d["streak"] == 1
    assert d["accuracy"] == 0.667 and sum(x["played"] for x in d["daily"]) == 3 and d["avg_time_ms"] == 4000
    assert c.get("/api/stats/team", headers=h).json()["played"] == 0
    r = c.get("/api/stats/card.png", headers=h)
    assert r.status_code == 200 and r.content[:4] == b"\x89PNG"
    assert c.get("/api/stats/card.png?scope=team", headers=h).status_code == 200
    assert c.get("/api/stats/me").status_code == 401


def test_streak_logic():
    from core.statsq import _streaks
    assert _streaks([1, 1, 0, 1, 1, 1]) == (3, 3)
    assert _streaks([1, 0.5, 1]) == (1, 1)
    assert _streaks([]) == (0, 0)


def admin_client(tmp_path):
    s, f, c = make(tmp_path, admin_id=7)
    return f, c, login(c, 7), login(c, 8)


def test_admin_requires_admin(tmp_path):
    f, c, adm, usr = admin_client(tmp_path)
    assert c.get("/api/admin/questions", headers=usr).status_code == 403
    assert c.get("/api/admin/questions", headers=adm).json()["total"] == 3
    assert c.get("/api/me", headers=adm).json()["is_admin"] is True
    assert c.get("/api/me", headers=usr).json()["is_admin"] is False


def test_admin_crud_hide_and_search(tmp_path):
    f, c, adm, _ = admin_client(tmp_path)
    body = {"text": "Новый вопрос про кота?", "answer": "Кот", "explanation": "Потому что кот", "tags": ["тест"]}
    assert c.post("/api/admin/questions", headers=adm, json=body).status_code == 200
    assert c.post("/api/admin/questions", headers=adm, json=body).status_code == 409      # дубль
    found = c.get("/api/admin/questions?q=КОТ", headers=adm).json()
    assert found["total"] == 1
    qid = found["items"][0]["id"]
    assert c.put(f"/api/admin/questions/{qid}", headers=adm, json={**body, "answer": "Кошка"}).status_code == 200
    assert c.get(f"/api/admin/questions/{qid}", headers=adm).json()["answer"] == "Кошка"
    assert c.post(f"/api/admin/questions/{qid}/hidden", headers=adm, json={"hidden": True}).status_code == 200
    assert c.get("/api/admin/questions?hidden=true", headers=adm).json()["total"] == 1
    # скрытый вопрос не выдаётся игрокам
    usr = login(c, 9)
    seen = {c.post("/api/solo/next", headers=usr).json()["question"]["id"] for _ in range(15)}
    assert qid not in seen
    assert c.delete(f"/api/admin/questions/{qid}", headers=adm).status_code == 200
    assert c.delete(f"/api/admin/questions/{qid}", headers=adm).status_code == 404


def test_admin_import_json_csv_and_errors(tmp_path):
    f, c, adm, _ = admin_client(tmp_path)
    js = json.dumps([{"text": "Q1?", "answer": "A1", "explanation": "E1"}, {"text": "Q2?", "answer": "A2"}], ensure_ascii=False)
    r = c.post("/api/admin/import", headers=adm, json={"format": "json", "content": js, "dry_run": True}).json()
    assert r["valid"] == 1 and r["added"] == 0 and r["errors"][0]["row"] == 2 and "explanation" in r["errors"][0]["reason"]
    assert c.post("/api/admin/import", headers=adm, json={"format": "json", "content": js}).json()["added"] == 1
    csv_text = "text,answer,explanation,accepted,difficulty\nВопрос 3?,А3,Е3,вар1|вар2,4\nВопрос 4?,А4,Е4,,9\n"
    r = c.post("/api/admin/import", headers=adm, json={"format": "csv", "content": csv_text}).json()
    assert r["added"] == 2
    assert QuestionRepo(f).get_full(next(i["id"] for i in c.get("/api/admin/questions?q=Вопрос 3", headers=adm).json()["items"]))["accepted"] == ["вар1", "вар2"]
    bad = c.post("/api/admin/import", headers=adm, json={"format": "json", "content": "{не json"}).json()
    assert bad["added"] == 0 and "JSON" in bad["errors"][0]["reason"]


def test_ws_start_clamps_bad_params(tmp_path):
    _, _, c = make(tmp_path)
    tok = ws_token(c, 7)
    with c.websocket_connect(f"/api/ws?token={tok}") as a:
        recv_state(a)
        a.send_json({"type": "start", "mode": "sport", "tours": 0, "per_tour": 0})
        st = recv_state(a)
        while not st["game"]:
            st = recv_state(a)
        assert st["game"]["tour"] == [1, 1] and st["game"]["total"] >= 1
