"""Прогон игрового цикла с подменённым Telegram-ботом и коротким таймером."""
import asyncio
import dataclasses
import shutil
from pathlib import Path

import pytest

from bot import main as M


class FakeBot:
    def __init__(self):
        self.sent, self.edits = [], []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append(text)
        return type("Msg", (), {"message_id": len(self.sent)})()

    async def send_photo(self, chat_id, photo, caption=None, **kw):
        self.sent.append(caption or "")
        return type("Msg", (), {"message_id": len(self.sent)})()

    async def edit_message_text(self, text, chat_id, message_id, **kw):
        self.edits.append(text)

    async def send_chat_action(self, *a, **kw):
        pass


@pytest.fixture
def game(tmp_path, monkeypatch):
    fake = FakeBot()
    monkeypatch.setattr(M, "bot", fake)
    monkeypatch.setattr(M, "cfg", dataclasses.replace(M.cfg, think_seconds=2, answer_seconds=1))
    monkeypatch.setattr(M, "stats", M.Stats(tmp_path / "s.sqlite"))
    monkeypatch.setattr(M, "llm", None)
    M.sessions.clear()
    return fake


def test_correct_answer_during_minute(game):
    async def run():
        await M.start_question(1, 42)
        s = M.sessions[42]
        await M.on_text(type("Msg", (), {"from_user": type("U", (), {"id": 42})(), "chat": type("C", (), {"id": 1})(),
                                          "text": s.q["answer"]})())
        return s.q
    q = asyncio.run(run())
    assert any("Верно" in t for t in game.sent)
    assert any(q["explanation"][:20] in t for t in game.sent)
    assert not M.sessions
    assert M.stats.summary(42)["points"] == 1


def test_timeout_flow_reveals_answer(game):
    async def run():
        await M.start_question(1, 7)
        await asyncio.sleep(4)  # 2 сек минута + 1 сек на ответ + запас
    asyncio.run(run())
    assert any("Время!" in t for t in game.sent)
    assert any("Правильный ответ" in t for t in game.sent)
    assert not M.sessions
    assert M.stats.summary(7) == {"played": 1, "points": 0, "correct": 0, "close": 0}


def test_second_question_blocked_while_active(game):
    async def run():
        await M.start_question(1, 5)
        await M.start_question(1, 5)
        M.sessions[5].task.cancel()
    asyncio.run(run())
    assert any("ещё не закончил" in t for t in game.sent)
