"""Командная игра, статистика вопросов, разбор по шагам и доступ по группам — с подменённым Telegram."""
import asyncio
import dataclasses
import json
from types import SimpleNamespace as NS

import pytest

from bot import main as M
from bot.storage import QuestionBank, Stats

CHAT, CAP, OTHER = -100500, 1, 2


class FakeBot:
    def __init__(self):
        self.sent, self.edits = [], []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append(text)
        return NS(message_id=len(self.sent) + 1000)

    async def send_photo(self, chat_id, photo, caption=None, **kw):
        self.sent.append(caption or "")
        return NS(message_id=len(self.sent) + 1000)

    async def send_animation(self, chat_id, animation, caption=None, **kw):
        self.sent.append(caption or "")
        return NS(message_id=len(self.sent) + 1000)

    async def edit_message_text(self, text, chat_id, message_id, **kw):
        self.edits.append(text)

    async def edit_message_caption(self, chat_id, message_id, caption=None, **kw):
        self.edits.append(caption or "")

    async def send_chat_action(self, *a, **kw):
        pass


def msg(user=CAP, text=None, name="Капитан", reply_to=None, chat=CHAT, chat_type="supergroup"):
    m = NS(chat=NS(id=chat, type=chat_type), from_user=NS(id=user, full_name=name, is_bot=False, username="u"),
           text=text, reply_to_message=reply_to, message_id=77, out=[])

    async def say(t, **kw):
        m.out.append(t)
    m.answer, m.reply = say, say
    return m


def cb(data, user=CAP, chat=CHAT):
    c = NS(data=data, from_user=NS(id=user, full_name="X", username="u"), message=NS(chat=NS(id=chat)), alerts=[])

    async def ans(text=None, show_alert=False):
        c.alerts.append(text)
    c.answer = ans
    return c


@pytest.fixture
def env(tmp_path, monkeypatch):
    fake = FakeBot()
    bank = QuestionBank(tmp_path / "q.json")
    bank.add([{"text": f"Вопрос номер {i}?", "answer": f"Ответ{i}", "explanation": f"Разбор{i}", "author": "Автор"} for i in range(6)])
    monkeypatch.setattr(M, "bot", fake)
    monkeypatch.setattr(M, "bank", bank)
    monkeypatch.setattr(M, "stats", Stats(tmp_path / "s.sqlite"))
    monkeypatch.setattr(M, "llm", None)
    monkeypatch.setattr(M, "TICK", 1)
    monkeypatch.setattr(M, "cfg", dataclasses.replace(M.cfg, think_seconds=2, team_answer_seconds=1, admin_id=999))
    M.games.clear()
    return fake


def run(coro):
    return asyncio.run(coro)


def test_full_team_game(env):
    async def play():
        await M.cmd_game(msg(), NS(args="2x2"))
        g = M.games[CHAT]
        assert (g.total, g.per_tour, g.captain_id) == (4, 2, CAP)
        answers = {q["id"]: q["answer"] for q in g.queue}
        # чужой игрок не может начать
        c = cb("tnext", user=OTHER)
        await M.cb_tnext(c)
        assert g.phase == "lobby" and "Решает капитан" in c.alerts[0]
        for i in range(4):
            await M.cb_tnext(cb("tnext"))
            assert g.phase == "think"
            wrong = i == 1                                           # второй вопрос провалим
            text = "неверно" if wrong else answers[g.current["id"]]
            # посторонний пытается ответить — не засчитывается
            other = msg(user=OTHER, text=text)
            await M.cmd_o(other, NS(args=text))
            assert "Ответ сдаёт капитан" in other.out[0] and g.phase == "think"
            await M.cmd_o(msg(text=f"/o {text}"), NS(args=text))
        return g

    g = run(play())
    assert M.games == {}                                              # игра закончилась и убрана
    texts = "\n".join(env.sent)
    assert "Конец тура" in texts and "Игра окончена" in texts
    assert "Тур 1: <b>1 из 2</b>" in texts and "Тур 2: <b>2 из 2</b>" in texts
    assert "Итого: <b>3 из 4</b>" in texts
    assert M.stats.summary(CHAT)["correct"] == 3 and M.stats.summary(CHAT)["played"] == 4   # статистика команды


def test_team_timeout_counts_as_miss_and_reply_answers(env):
    async def play():
        await M.cmd_game(msg(), NS(args="1x2"))
        g = M.games[CHAT]
        await M.cb_tnext(cb("tnext"))
        await asyncio.sleep(2 + 1 + 1.5)          # минута + окно ответа вышли
        assert g.results[0] is False and g.phase == "between"
        await M.cb_tnext(cb("tnext"))
        await asyncio.sleep(2.5)                  # минута закончилась — бот ждёт ответ
        assert g.phase == "answer"
        reply = msg(text=g.current["answer"], reply_to=NS(message_id=g.answer_msg_id))
        await M.on_team_reply(reply)              # ответ реплаем на сообщение бота
        return g
    g = run(play())
    assert g.results == [False, True] and M.games == {}


def test_stop_and_captain_rules(env):
    async def play():
        await M.cmd_game(msg(), NS(args="1x3"))
        g = M.games[CHAT]
        m = msg(user=OTHER, name="Игрок")
        await M.cmd_stop(m)                                        # не капитан
        assert "может капитан" in m.out[0] and CHAT in M.games
        # капитан передаёт роль ответом на сообщение игрока
        await M.cmd_captain(msg(reply_to=NS(from_user=NS(id=OTHER, full_name="Игрок", is_bot=False))))
        assert g.captain_id == OTHER
        m2 = msg(user=CAP)
        await M.cmd_captain(m2)                                    # в лобби можно забрать роль себе
        assert g.captain_id == CAP
        await M.cb_tnext(cb("tnext"))
        m3 = msg(user=OTHER)
        await M.cmd_captain(m3)                                    # во время вопроса — нельзя
        assert "нельзя" in m3.out[0] and g.captain_id == CAP
        stop = msg()
        await M.cmd_stop(stop)
        return stop
    stop = run(play())
    assert M.games == {} and "Игра остановлена" in stop.out[0]


def test_game_not_in_private_and_no_double_game(env):
    m = msg(chat=5, chat_type="private")
    run(M.team_only_in_groups(m))
    assert "групповом чате" in m.out[0]

    async def play():
        await M.cmd_game(msg(), NS(args=None))
        again = msg()
        await M.cmd_game(again, NS(args=None))
        return again
    assert "уже идёт игра" in run(play()).out[0]


def test_parse_game_args():
    assert M.parse_game_args("2x10") == (2, 10) and M.parse_game_args("3х12") == (3, 12)   # русская «х»
    assert M.parse_game_args(None) == (M.cfg.team_tours, M.cfg.team_per_tour)
    assert M.parse_game_args("99x99") == (6, 20)


def test_steps_button_generates_once_and_caches(env, monkeypatch):
    calls = []

    class LLM:
        messages = None

        def __init__(self):
            self.messages = self

        async def create(self, **kw):
            calls.append(1)
            body = {"steps": [{"clue": "зацепка", "inference": "вывод", "how": "логика"}], "lesson": "урок"}
            return NS(content=[NS(text=json.dumps(body))])

    monkeypatch.setattr(M, "llm", LLM())
    qid = M.bank.items[0]["id"]

    async def play():
        await M.cb_steps(cb(f"steps:{qid}"))
        await M.cb_steps(cb(f"steps:{qid}"))
    run(play())
    assert len(calls) == 1                                           # второй раз — из кэша
    assert "Разбор по шагам" in env.sent[0] and "1️⃣" in env.sent[1] and M.bank.get(qid)["steps"]["lesson"] == "урок"


def test_steps_without_llm_falls_back_to_author_comment(env):
    qid = M.bank.items[0]["id"]
    run(M.cb_steps(cb(f"steps:{qid}")))
    assert "Шаги сейчас недоступны" in env.sent[0] and "Разбор0" in env.sent[0]


def test_rate_line_and_qstats(env):
    q = M.bank.items[0]
    for u, s in ((10, 1.0), (11, 1.0), (12, 0.0)):
        M.stats.record(u, q["id"], s, "a")
    parts = M.result_parts(q, "head", "a", "c")
    assert any("берут 67%" in p for p in parts)
    m = msg(user=999)
    run(M.cmd_qstats(m))
    assert "Самые сложные" in m.out[0] and "67%" in m.out[0]
    stranger = msg(user=5)
    run(M.cmd_qstats(stranger))
    assert stranger.out == []                                         # только админ


def test_access_by_group(monkeypatch):
    monkeypatch.setattr(M, "cfg", dataclasses.replace(M.cfg, admin_id=99))
    monkeypatch.setattr(M, "ALLOWED", {1})
    monkeypatch.setattr(M, "ALLOWED_CHATS", {-5})
    assert M.is_allowed(7, -5, "supergroup")           # любой участник разрешённой группы
    assert not M.is_allowed(7, -6, "supergroup")       # чужая группа
    assert not M.is_allowed(7, 7, "private")           # а в личке — только по списку
    assert M.is_allowed(1, -6, "supergroup") and M.is_allowed(99, 7, "private")
    monkeypatch.setattr(M, "ALLOWED", set())
    monkeypatch.setattr(M, "ALLOWED_CHATS", set())
    assert M.is_allowed(7, 7, "private")               # ничего не задано — открыт всем


def test_guard_silent_in_foreign_group_and_myid_always_works(monkeypatch):
    monkeypatch.setattr(M, "ALLOWED", {1})
    monkeypatch.setattr(M, "ALLOWED_CHATS", set())
    monkeypatch.setattr(M, "cfg", dataclasses.replace(M.cfg, admin_id=99))
    seen = []

    async def handler(event, data):
        seen.append(event.text)

    class Ev(M.Message):  # настоящий Message не нужен: Guard смотрит на атрибуты
        pass

    def event(text, chat_type):
        e = NS(text=text, from_user=NS(id=7, username="x", full_name="Чужой"), chat=NS(id=-9, type=chat_type), out=[])

        async def say(t, **kw):
            e.out.append(t)
        e.answer = say
        return e

    # Guard проверяет isinstance(event, Message): подменяем Message на NS-подобный класс для теста
    monkeypatch.setattr(M, "Message", NS)
    g = M.Guard()
    grp = event("/game", "supergroup")
    run(g(handler, grp, {}))
    assert seen == [] and grp.out == []                # в чужой группе — тишина
    run(g(handler, event("/myid", "supergroup"), {}))
    assert seen == ["/myid"]                           # /myid доступен всем
    priv = event("/start", "private")
    run(g(handler, priv, {}))
    assert priv.out == ["Бот приватный: доступ только для команды."]
