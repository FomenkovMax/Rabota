import asyncio
import dataclasses
import json
import shutil
from pathlib import Path

import pytest

from bot import judge as J
from bot.llm import extract_json
from bot.storage import QuestionBank, Stats

SEED = Path(__file__).resolve().parent.parent / "bot" / "seed_questions.json"
Q = json.loads(SEED.read_text(encoding="utf-8"))[0]  # пенициллин


class FakeLLM:
    """Подменяет AsyncAnthropic: messages.create возвращает заранее заданный текст."""
    def __init__(self, text):
        self.text, self.calls = text, 0
        self.messages = self

    async def create(self, **kw):
        self.calls += 1
        return type("R", (), {"content": [type("B", (), {"text": self.text})()]})()


def test_extract_json_handles_fences():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Вот: [{"a": 1}] готово') == [{"a": 1}]
    with pytest.raises(ValueError):
        extract_json("нет json")


def test_quick_check_normalizes():
    assert J.quick_check(Q, "  пенициллин!! ")
    assert J.quick_check(Q, "Penicillin")
    assert not J.quick_check(Q, "антибиотик")
    assert not J.quick_check(Q, "")


def test_judge_exact_match_skips_llm():
    llm = FakeLLM("")
    v = asyncio.run(J.judge(llm, "m", Q, "Пенициллин"))
    assert v.level == "correct" and llm.calls == 0


def test_judge_uses_llm_verdicts():
    for level, score in (("correct", 1.0), ("close", 0.5), ("wrong", 0.0)):
        llm = FakeLLM(json.dumps({"level": level, "comment": "ок"}))
        v = asyncio.run(J.judge(llm, "m", Q, "антибиотик"))
        assert (v.level, v.score) == (level, score) and llm.calls == 1


def test_judge_bad_llm_output_falls_back():
    v = asyncio.run(J.judge(FakeLLM("не json"), "m", Q, "пенецилин"))  # опечатка
    assert v.level == "correct"
    v = asyncio.run(J.judge(FakeLLM("не json"), "m", Q, "хлеб"))
    assert v.level == "wrong"


def test_bank_add_dedupes_and_rejects_incomplete(tmp_path):
    bank = QuestionBank(tmp_path / "q.json", seed=SEED)
    n = len(bank.items)
    new = {"text": "Новый?", "answer": "Да", "explanation": "Потому что."}
    assert bank.add([new, new, {"text": "без ответа"}]) == 1
    assert len(QuestionBank(tmp_path / "q.json").items) == n + 1


def test_pick_prefers_unseen_and_repeats_when_exhausted(tmp_path):
    bank = QuestionBank(tmp_path / "q.json", seed=SEED)
    ids = [q["id"] for q in bank.items]
    q, fresh = bank.pick(set(ids[:-1]))
    assert q["id"] == ids[-1] and fresh == 1
    q, fresh = bank.pick(set(ids))
    assert q is not None and fresh == 0


def test_stats(tmp_path):
    st = Stats(tmp_path / "s.sqlite")
    st.record(1, "a", 1.0, "x")
    st.record(1, "b", 0.5, "y")
    st.record(1, "c", 0.0, None)
    assert st.seen(1) == {"a", "b", "c"}
    assert st.summary(1) == {"played": 3, "points": 1.5, "correct": 1, "close": 1}
    assert st.summary(2)["played"] == 0


def test_judge_timeout_falls_back(monkeypatch):
    class Slow(FakeLLM):
        async def create(self, **kw):
            await asyncio.sleep(5)

    monkeypatch.setattr(J, "JUDGE_TIMEOUT", 0.1)
    v = asyncio.run(J.judge(Slow(""), "m", Q, "хлеб"))
    assert v.level == "wrong"  # не зависли и не упали
