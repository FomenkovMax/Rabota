import json
import sqlite3
from datetime import datetime, timedelta, timezone

from radar.db import DB
from radar.dedup import PostGroup, match_history_posts, merge_event_into, same_event
from radar.event_dedup import dedup_events
from radar.llm.client import LLMClient, LLMResult
from radar.sources.base import Post


def mk(ch, pid, text):
    return Post(ch, pid, f"https://t.me/{ch}/{pid}", text, datetime.now(timezone.utc))


def E(title, summary, org="ООО Ромашка", amounts=(), score=4, cat=1, urls=("https://t.me/a/1",), ch=("a",)):
    return {"category": cat, "title": title, "summary": summary, "relevance_score": score,
            "organizations": [{"name": org, "inn_if_in_text": None}], "amounts": list(amounts),
            "source_urls": list(urls), "channels": list(ch), "post_keys": [u.split("t.me/")[1] for u in urls]}


# ------------------------------------------------------------------ смысловое сопоставление
def test_paraphrase_same_org_and_amount_is_same_event():
    a = E("Открылся филиал ООО Ромашка в Луганске", "Компания вложила 99 млн рублей и создала 120 рабочих мест", amounts=["99 млн руб."])
    b = E("Ромашка запустила новое производство", "Инвестиции составили 99 млн, появится 120 вакансий", amounts=["99 млн"])
    assert same_event(a, b) == "yes"


def test_different_facts_about_same_org_are_not_merged():
    a = E("Ромашка открыла филиал", "Открыт филиал в Луганске, 120 рабочих мест", amounts=["99 млн"])
    b = E("Суд арестовал счета Ромашки", "Арбитраж наложил арест из-за долга по налогам", amounts=["5 млн"], cat=3)
    assert same_event(a, b) in ("no", "maybe")           # максимум — на проверку LLM, но не «yes»


def test_different_orgs_same_numbers_not_same():
    a = E("Завод А построит цех", "Инвестиции 500 млн", org="ООО Завод А", amounts=["500 млн"])
    b = E("Банк Б открыл отделение", "Вложено 500 млн", org="ПАО Банк Б", amounts=["500 млн"])
    assert same_event(a, b) == "no"


def test_merge_event_into_collects_sources_and_max_score():
    a = E("t", "s", score=3, urls=("https://t.me/a/1",), ch=("a",))
    b = E("t", "s", score=5, urls=("https://t.me/b/9",), ch=("b",))
    b["image_url"] = "https://cdn1.telesco.pe/x.jpg"
    merge_event_into(a, b)
    assert a["source_urls"] == ["https://t.me/a/1", "https://t.me/b/9"] and a["channels"] == ["a", "b"]
    assert a["relevance_score"] == 5 and a["image_url"]


# ------------------------------------------------------------------ посты прошлых дней
TEXT = "В Луганске открылся новый филиал сети магазинов «Продукты», в нём будут работать 120 сотрудников"


def test_history_post_repeat_attaches_to_event_or_skips_irrelevant():
    hist = [{"channel": "a", "post_id": 1, "text": TEXT, "event_id": 7},
            {"channel": "a", "post_id": 2, "text": "Погода на завтра: дождь и сильный ветер, температура около десяти градусов", "event_id": None}]
    groups = [PostGroup([mk("b", 5, "🔥 " + TEXT + "!")]),
              PostGroup([mk("c", 6, "Погода на завтра: дождь и сильный ветер, температура около десяти градусов")]),
              PostGroup([mk("d", 7, "Правительство утвердило программу развития дорожной сети на три года вперёд")])]
    fresh, attach, skipped = match_history_posts(groups, hist, 88)
    assert len(fresh) == 1 and fresh[0].main.channel == "d"
    assert list(attach) == [7] and skipped == 1


# ------------------------------------------------------------------ события: внутри запуска и с историей
class SameLLM(LLMClient):
    def __init__(self, answer):
        self.answer, self.calls = answer, 0

    async def complete(self, model, system, user, max_tokens=1500):
        self.calls += 1
        return LLMResult(json.dumps({"same": self.answer}), 10, 2)


class FakeClf:
    def __init__(self, answer):
        self.answer, self.calls = answer, 0

    async def same_news(self, a, b):
        self.calls += 1
        return self.answer


async def test_events_dedup_inside_run_and_against_history(tmp_path):
    db = DB(tmp_path / "t.db")
    old = E("Открылся филиал Ромашки", "Вложено 99 млн, 120 мест", amounts=["99 млн"], urls=("https://t.me/a/1",))
    old["id"] = db.save_event(1, old)
    new1 = E("Ромашка запустила производство", "Инвестиции 99 млн", amounts=["99 млн"], urls=("https://t.me/b/5",), ch=("b",))
    new2 = E("Ромашка: новое производство", "Те же 99 млн", amounts=["99 млн"], urls=("https://t.me/c/6",), ch=("c",))
    other = E("Правительство утвердило бюджет", "Принят бюджет региона", org="Правительство ЛНР", urls=("https://t.me/d/7",), ch=("d",))
    fresh, inside, attached = await dedup_events([new1, new2, other], [old], None, db)
    assert [e["title"] for e in fresh] == ["Правительство утвердило бюджет"]    # старую новость заново не показываем
    assert attached == 1 and inside == 1
    stored = db.get_event(old["id"])
    assert set(stored["source_urls"]) == {"https://t.me/a/1", "https://t.me/b/5", "https://t.me/c/6"}


async def test_maybe_pairs_go_to_llm_and_budget_is_respected():
    a = E("Ромашка начала поставки", "Поставки продуктов в магазины Луганска начались сегодня")
    b = E("Ромашка расширяет поставки", "Компания расширяет географию поставок продуктов на новые районы")
    assert same_event(a, b) == "maybe"
    yes, no = FakeClf(True), FakeClf(False)
    assert (await dedup_events([dict(b)], [dict(a, id=1)], yes, None))[2] == 1
    assert (await dedup_events([dict(b)], [dict(a, id=1)], no, None))[0] != []
    zero = FakeClf(True)
    out, _, att = await dedup_events([dict(b)], [dict(a, id=1)], zero, None, max_llm_calls=0)
    assert zero.calls == 0 and att == 0 and len(out) == 1       # бюджет исчерпан — не склеиваем (лучше повтор, чем потеря)


# ------------------------------------------------------------------ база
def test_db_migrates_old_posts_table_and_links_posts(tmp_path):
    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.executescript("CREATE TABLE posts (channel TEXT NOT NULL, post_id INTEGER NOT NULL, url TEXT, text TEXT,"
                    " published_at TEXT, fetched_at TEXT, run_id INTEGER, PRIMARY KEY (channel, post_id));"
                    "INSERT INTO posts VALUES ('a', 1, 'u', 'text', 'p', '2999-01-01T00:00:00+00:00', 1);")
    c.commit()
    c.close()
    db = DB(path)                                              # не падает на старой схеме
    db.link_posts(5, ["a/1", "bad-key"])
    assert db.recent_posts(3)[0]["event_id"] == 5


# ------------------------------------------------------------------ сквозной сценарий: два запуска, два канала
class ParaLLM(LLMClient):
    """Фильтр: всё релевантно. Разбор: заголовок = начало текста, организация и сумма одни и те же."""
    async def complete(self, model, system, user, max_tokens=1500):
        if "ОДНО И ТО ЖЕ" in system:
            return LLMResult(json.dumps({"same": False}), 5, 1)
        if "фильтр" in system:
            n = user.count("\n[") + 1
            return LLMResult(json.dumps({"results": [{"i": i, "relevant": True} for i in range(n)]}), 50, 5)
        text = user.split("Новость:\n", 1)[1]
        return LLMResult(json.dumps({"category": 1, "title": text[:45], "summary": text[:90],
                                     "organizations": [{"name": "ООО Ромашка", "inn_if_in_text": None}],
                                     "amounts": ["99 млн рублей"], "relevance_score": 5}), 100, 40)


class PostsSource:
    def __init__(self, posts):
        self.posts = posts

    async def fetch(self, ch, since):
        return [p for p in self.posts if p.channel == ch]

    async def polite_pause(self): pass
    async def aclose(self): pass


async def test_same_news_from_other_channel_hours_later_is_not_shown_again(tmp_path, monkeypatch):
    from radar import pipeline
    monkeypatch.setattr(pipeline, "make_client", lambda env: ParaLLM())
    monkeypatch.setattr(pipeline, "build_adapters", lambda env, cfg: [])          # без сети (DaData)
    monkeypatch.setattr(pipeline, "load_channels", lambda: [{"username": "a"}, {"username": "b"}])
    async def no_pdf(*a, **k): return None
    monkeypatch.setattr(pipeline, "make_onepager", no_pdf)
    monkeypatch.setattr(pipeline, "export_files", lambda *a, **k: [])
    db = DB(tmp_path / "t.db")

    textA = "В Луганске открылся новый филиал ООО Ромашка: компания вложила 99 млн рублей в запуск производства"
    textB = "Предприятие ООО Ромашка запустило новую площадку, инвестиции составили 99 млн рублей, подробности ниже"
    r1 = await pipeline.run_once(db, hours=24, source=PostsSource([mk("a", 1, textA)]))
    assert len(r1.events) == 1
    # прошло несколько часов, второй канал пишет ту же новость другими словами
    r2 = await pipeline.run_once(db, hours=24, source=PostsSource([mk("b", 7, textB)]))
    assert r2.events == []                                    # НЕ новость: в дайджест повторно не попадает
    assert "Новых значимых событий нет" in r2.digest
    stored = db.recent_events(3)
    assert len(stored) == 1 and len(stored[0]["source_urls"]) == 2       # зато у старого события стало 2 источника
    # и третий запуск с тем же пересказом из третьего места не создаёт события
    r3 = await pipeline.run_once(db, hours=24, source=PostsSource([mk("a", 9, textB + " Подробнее на сайте.")]))
    assert r3.events == []


async def test_genuinely_new_news_about_same_org_is_still_shown(tmp_path, monkeypatch):
    from radar import pipeline
    monkeypatch.setattr(pipeline, "make_client", lambda env: ParaLLM())
    monkeypatch.setattr(pipeline, "build_adapters", lambda env, cfg: [])
    monkeypatch.setattr(pipeline, "load_channels", lambda: [{"username": "a"}, {"username": "b"}])
    async def no_pdf(*a, **k): return None
    monkeypatch.setattr(pipeline, "make_onepager", no_pdf)
    monkeypatch.setattr(pipeline, "export_files", lambda *a, **k: [])
    db = DB(tmp_path / "t.db")
    await pipeline.run_once(db, hours=24, source=PostsSource([mk("a", 1, "ООО Ромашка открыла филиал в Луганске и вложила 99 млн рублей")]))
    r2 = await pipeline.run_once(db, hours=24, source=PostsSource([mk("b", 2, "Против ООО Ромашка подан иск о банкротстве, долг составляет 7 млн рублей")]))
    assert len(r2.events) == 1                                 # другое событие — показываем
