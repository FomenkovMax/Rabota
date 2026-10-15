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
