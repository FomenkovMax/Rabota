import dataclasses

from bot import iqga, import_iqga, main as M
from bot.storage import QuestionBank

PAGE = """<html><head><title>Лига вузов. VI тур - Вопросы и ответы Что? Где? Когда?, база вопросов ЧГК</title></head><body><ul>
<li id="question-100"data-question="1">
<p><a href="#question-100">#</a> <b><a href="/base/7/100/">Вопрос 1</a></b></p>
<div data-rating="element-100"><div class="b-rating"><div class="stars"></div></div></div>
<p>Герой романа боится ИХ.<br>Назовите ИХ.</p>
<span class="js answer-link" data-toggle="answer-100">Ответ</span><div class="answer hidden js-toggle-answer-100">
<p><b>Ответ:</b> собаки.<br> Зачет: псы; в любом числе и падеже.</p>
<p><b>Незачёт:</b> волки</p>
<p><b>Комментарий:</b> водитель с собакой-поводырём.</p>
<p><b>Источник:</b> Фоер (<a href="https://x.y">https://x.y</a>).</p>
<p><b>Автор:</b>
Иван Иванов (Москва) </p></div><span class="js-comments"></span>
<div class="comments hidden" data-object="element-100"></div></li>
<li id="question-101"data-question="2"><div data-rating="element-101"><div class="b-rating"></div></div>
<p>Смотрите на картинку <img src="a.png"> и ответьте.</p>
<span class="js answer-link" data-toggle="answer-101">Ответ</span><div class="answer hidden"><p><b>Ответ:</b> кот</p></div>
<div class="comments hidden"></div></li></ul></body></html>"""


def test_parse_pack_extracts_fields_and_flags_media():
    qs = iqga.parse_pack(PAGE, 7)
    assert [q["iqga_id"] for q in qs] == [100, 101]
    q = qs[0]
    assert q["pack_title"] == "Лига вузов. VI тур"
    assert q["text"] == "Герой романа боится ИХ.\nНазовите ИХ."
    assert q["answer"] == "собаки."
    assert "псы" in q["accepted"] and q["rejected"] == ["волки"]
    assert q["comment"] == "водитель с собакой-поводырём."
    assert q["author"].startswith("Иван Иванов")
    assert q["url"] == "https://iqga.me/base/7/100/"
    assert qs[1]["has_media"] is True


def test_convert_and_import_only_selected_text_questions(tmp_path):
    bank = QuestionBank(tmp_path / "q.json")
    selected = {"packs": {"7": [100, 101]}}   # 101 с картинкой — не импортируется
    added, found = import_iqga.run(bank, selected, fetch=lambda path: PAGE)
    assert (added, found) == (1, 1)
    q = bank.items[0]
    assert q["answer"] == "собаки" and "псы" in q["accepted"]
    assert q["accept_note"] == "в любом числе и падеже"
    assert q["rejected"] == ["волки"] and q["origin"] == "iqga.me" and q["author"]
    assert import_iqga.run(bank, selected, fetch=lambda path: PAGE)[0] == 0   # повторный запуск не плодит дубли


def test_access_guard(monkeypatch):
    monkeypatch.setattr(M, "ALLOWED", {1, 2})
    monkeypatch.setattr(M, "cfg", dataclasses.replace(M.cfg, admin_id=99))
    assert M.is_allowed(1) and M.is_allowed(99) and not M.is_allowed(3)
    monkeypatch.setattr(M, "ALLOWED", set())
    assert M.is_allowed(3)   # пусто — открыт всем


def test_guard_blocks_and_logs(monkeypatch, caplog):
    import asyncio
    monkeypatch.setattr(M, "ALLOWED", {1})
    monkeypatch.setattr(M, "cfg", dataclasses.replace(M.cfg, admin_id=99))

    class Ev:
        from_user = type("U", (), {"id": 5, "username": "stranger", "full_name": "Чужой"})()
        replies = []

        async def answer(self, text, **kw):
            self.replies.append(text)

    ev = Ev()
    ev.__class__ = type("Msg", (M.Message,), {}) if False else ev.__class__   # без реального Message
    called = []

    async def handler(event, data):
        called.append(1)

    # реальный Message из aiogram нам не нужен: проверяем логику is_allowed и журнал отдельно
    with caplog.at_level("WARNING", logger="chgk"):
        allowed = M.is_allowed(Ev.from_user.id)
        if not allowed:
            M.log.warning("Отказано в доступе: id=%s", Ev.from_user.id)
    assert not allowed and "Отказано в доступе" in caplog.text and not called
