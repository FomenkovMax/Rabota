"""SQLite: posts, events, organizations (кэш), runs, subscribers. Синхронный sqlite3 — для нашего объёма достаточно."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL, finished_at TEXT, status TEXT,
  posts_new INTEGER DEFAULT 0, events_n INTEGER DEFAULT 0,
  tokens_in INTEGER DEFAULT 0, tokens_out INTEGER DEFAULT 0, cost_usd REAL,
  channel_errors TEXT DEFAULT '{}',     -- JSON {channel: ошибка}
  tokens_spent INTEGER, tokens_left INTEGER   -- расход/остаток токенов у LLM-сервиса по данным баланса
);
CREATE TABLE IF NOT EXISTS posts (
  channel TEXT NOT NULL, post_id INTEGER NOT NULL,
  url TEXT, text TEXT, published_at TEXT, fetched_at TEXT, run_id INTEGER,
  event_id INTEGER,                      -- к какому событию отнесён пост (NULL = нерелевантный)
  PRIMARY KEY (channel, post_id)         -- дедупликация по (channel, post_id)
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, created_at TEXT,
  category INTEGER, score INTEGER, title TEXT, data TEXT,  -- data = JSON события целиком
  sent_at TEXT                                              -- когда показано в ежедневном дайджесте (NULL = ещё нет)
);
CREATE TABLE IF NOT EXISTS feedback (          -- оценки полезности новостей от коллег (кнопки 1–5)
  event_id INTEGER NOT NULL, user_id INTEGER NOT NULL, score INTEGER NOT NULL, created_at TEXT,
  PRIMARY KEY (event_id, user_id)              -- один голос на человека; можно переголосовать
);
CREATE TABLE IF NOT EXISTS organizations (
  key TEXT PRIMARY KEY,                  -- ИНН или нормализованное название
  data TEXT NOT NULL, fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS subscribers (
  user_id INTEGER PRIMARY KEY, dm_enabled INTEGER DEFAULT 1
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DB:
    def __init__(self, path: Path):
        self.path = path
        with self.conn() as c:
            c.executescript(SCHEMA)
            # миграция для баз, созданных до появления event_id
            if "event_id" not in {r["name"] for r in c.execute("PRAGMA table_info(posts)")}:
                c.execute("ALTER TABLE posts ADD COLUMN event_id INTEGER")
            # sent_at: все уже существующие события считаем показанными (иначе при обновлении в дайджест
            # хлынет вся старая лента)
            if "sent_at" not in {r["name"] for r in c.execute("PRAGMA table_info(events)")}:
                c.execute("ALTER TABLE events ADD COLUMN sent_at TEXT")
                c.execute("UPDATE events SET sent_at = COALESCE(created_at, ?)", (now_iso(),))
            run_cols = {r["name"] for r in c.execute("PRAGMA table_info(runs)")}
            for col in ("tokens_spent", "tokens_left"):
                if col not in run_cols:
                    c.execute(f"ALTER TABLE runs ADD COLUMN {col} INTEGER")

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()

    # ---- runs ----
    def start_run(self) -> int:
        with self.conn() as c:
            return c.execute("INSERT INTO runs(started_at, status) VALUES (?, 'running')", (now_iso(),)).lastrowid

    def finish_run(self, run_id: int, status: str, **f) -> None:
        with self.conn() as c:
            c.execute(
                "UPDATE runs SET finished_at=?, status=?, posts_new=?, events_n=?, tokens_in=?, tokens_out=?,"
                " cost_usd=?, channel_errors=?, tokens_spent=?, tokens_left=? WHERE id=?",
                (now_iso(), status, f.get("posts_new", 0), f.get("events_n", 0), f.get("tokens_in", 0),
                 f.get("tokens_out", 0), f.get("cost_usd"), json.dumps(f.get("channel_errors", {}), ensure_ascii=False),
                 f.get("tokens_spent"), f.get("tokens_left"), run_id))

    def last_success(self) -> datetime | None:
        """Время начала последнего успешного запуска — от него берём новые посты."""
        with self.conn() as c:
            r = c.execute("SELECT started_at FROM runs WHERE status='ok' ORDER BY id DESC LIMIT 1").fetchone()
        return datetime.fromisoformat(r["started_at"]) if r else None

    # ---- posts ----
    def known_posts(self, channel: str, ids: list[int]) -> set[int]:
        if not ids:
            return set()
        q = ",".join("?" * len(ids))
        with self.conn() as c:
            rows = c.execute(f"SELECT post_id FROM posts WHERE channel=? AND post_id IN ({q})", (channel, *ids))
            return {r["post_id"] for r in rows}

    def save_posts(self, posts, run_id: int) -> None:
        with self.conn() as c:
            c.executemany(
                "INSERT OR IGNORE INTO posts(channel, post_id, url, text, published_at, fetched_at, run_id)"
                " VALUES (?,?,?,?,?,?,?)",
                [(p.channel, p.post_id, p.url, p.text, p.published_at.isoformat(), now_iso(), run_id) for p in posts])

    def link_posts(self, event_id: int, keys: list[str]) -> None:
        """Привязывает посты (ключи вида 'канал/id') к событию — чтобы повтор через сутки узнавался."""
        rows = []
        for k in keys:
            ch, _, pid = k.rpartition("/")
            if ch and pid.isdigit():
                rows.append((event_id, ch, int(pid)))
        if rows:
            with self.conn() as c:
                c.executemany("UPDATE posts SET event_id=? WHERE channel=? AND post_id=?", rows)

    def recent_posts(self, days: float) -> list[dict]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        with self.conn() as c:
            rows = c.execute("SELECT channel, post_id, url, text, event_id FROM posts WHERE fetched_at >= ?", (cutoff,))
            return [dict(r) for r in rows]

    # ---- events ----
    def recent_events(self, days: float) -> list[dict]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        with self.conn() as c:
            rows = c.execute("SELECT id, data FROM events WHERE created_at >= ?", (cutoff,)).fetchall()
        out = []
        for r in rows:
            ev = json.loads(r["data"])
            ev["id"] = r["id"]
            out.append(ev)
        return out

    def get_event(self, event_id: int) -> dict | None:
        with self.conn() as c:
            r = c.execute("SELECT id, data FROM events WHERE id=?", (event_id,)).fetchone()
        return {**json.loads(r["data"]), "id": r["id"]} if r else None

    def update_event(self, event_id: int, ev: dict) -> None:
        with self.conn() as c:
            c.execute("UPDATE events SET data=?, title=?, score=? WHERE id=?",
                      (json.dumps(ev, ensure_ascii=False), ev.get("title"), ev.get("relevance_score"), event_id))

    def save_event(self, run_id: int, ev: dict) -> int:
        with self.conn() as c:
            return c.execute(
                "INSERT INTO events(run_id, created_at, category, score, title, data) VALUES (?,?,?,?,?,?)",
                (run_id, now_iso(), ev.get("category"), ev.get("relevance_score"), ev.get("title"),
                 json.dumps(ev, ensure_ascii=False))).lastrowid

    # ---- ежедневный дайджест: что ещё не показывали ----
    def unsent_events(self) -> list[dict]:
        with self.conn() as c:
            rows = c.execute("SELECT id, data FROM events WHERE sent_at IS NULL ORDER BY id").fetchall()
        return [{**json.loads(r["data"]), "id": r["id"]} for r in rows]

    def mark_sent(self, event_ids: list[int]) -> None:
        if event_ids:
            with self.conn() as c:
                c.executemany("UPDATE events SET sent_at=? WHERE id=?", [(now_iso(), i) for i in event_ids])

    def spent_since(self, ts_iso: str) -> int | None:
        """Сколько токенов списано запусками с момента ts (по данным баланса). None — данных баланса нет."""
        with self.conn() as c:
            r = c.execute("SELECT SUM(tokens_spent) AS s, COUNT(tokens_spent) AS n FROM runs"
                          " WHERE started_at >= ? AND status='ok'", (ts_iso,)).fetchone()
        return int(r["s"]) if r["n"] else None

    def channel_errors_since(self, ts_iso: str) -> dict:
        """Каналы, не читавшиеся в запусках с момента ts (объединение по запускам)."""
        with self.conn() as c:
            rows = c.execute("SELECT channel_errors FROM runs WHERE started_at >= ?", (ts_iso,)).fetchall()
        out: dict = {}
        for r in rows:
            try:
                out.update(json.loads(r["channel_errors"] or "{}"))
            except ValueError:
                pass
        return out

    # ---- оценки полезности (кнопки под новостями) ----
    def set_vote(self, event_id: int, user_id: int, score: int) -> None:
        if not 1 <= score <= 5:
            raise ValueError("оценка должна быть от 1 до 5")
        with self.conn() as c:
            c.execute("INSERT INTO feedback(event_id, user_id, score, created_at) VALUES (?,?,?,?)"
                      " ON CONFLICT(event_id, user_id) DO UPDATE SET score=excluded.score, created_at=excluded.created_at",
                      (event_id, user_id, score, now_iso()))

    def vote_stats(self, event_id: int) -> tuple[float | None, int]:
        """(средняя оценка, число голосов) по новости."""
        with self.conn() as c:
            r = c.execute("SELECT AVG(score) AS a, COUNT(*) AS n FROM feedback WHERE event_id=?", (event_id,)).fetchone()
        return (float(r["a"]) if r["n"] else None), int(r["n"])

    def feedback_rows(self) -> list[dict]:
        """Новости, получившие хотя бы один голос: оценка модели, средняя оценка коллег, число голосов."""
        with self.conn() as c:
            rows = c.execute(
                "SELECT e.id, e.category, e.score AS llm, e.title, e.data, AVG(f.score) AS avg, COUNT(f.score) AS n"
                " FROM events e JOIN feedback f ON f.event_id = e.id GROUP BY e.id ORDER BY e.id").fetchall()
        out = []
        for r in rows:
            d = json.loads(r["data"])
            out.append({"id": r["id"], "category": r["category"], "llm": r["llm"], "title": r["title"],
                        "avg": float(r["avg"]), "n": int(r["n"]), "channels": d.get("channels") or []})
        return out

    # ---- organizations (кэш обогащения) ----
    def cache_get(self, key: str, ttl_days: int) -> dict | None:
        with self.conn() as c:
            r = c.execute("SELECT data, fetched_at FROM organizations WHERE key=?", (key,)).fetchone()
        if not r:
            return None
        age = datetime.now(timezone.utc) - datetime.fromisoformat(r["fetched_at"])
        return json.loads(r["data"]) if age.days < ttl_days else None

    def cache_put(self, key: str, data: dict) -> None:
        with self.conn() as c:
            c.execute("INSERT OR REPLACE INTO organizations(key, data, fetched_at) VALUES (?,?,?)",
                      (key, json.dumps(data, ensure_ascii=False), now_iso()))

    # ---- meta: служебные значения (например, когда последний раз предупреждали о малом балансе) ----
    def get_meta(self, key: str) -> str | None:
        with self.conn() as c:
            r = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r["value"] if r else None

    def set_meta(self, key: str, value: str) -> None:
        with self.conn() as c:
            c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))

    # ---- subscribers (/mute, /unmute) ----
    def set_dm(self, user_id: int, enabled: bool) -> None:
        with self.conn() as c:
            c.execute("INSERT INTO subscribers(user_id, dm_enabled) VALUES (?,?)"
                      " ON CONFLICT(user_id) DO UPDATE SET dm_enabled=excluded.dm_enabled", (user_id, int(enabled)))

    def dm_muted(self) -> set[int]:
        with self.conn() as c:
            return {r["user_id"] for r in c.execute("SELECT user_id FROM subscribers WHERE dm_enabled=0")}

    # ---- stats ----
    def stats(self) -> dict:
        with self.conn() as c:
            q = lambda s: c.execute(s).fetchone()[0]  # noqa: E731
            return {"posts": q("SELECT COUNT(*) FROM posts"), "events": q("SELECT COUNT(*) FROM events"),
                    "runs": q("SELECT COUNT(*) FROM runs"),
                    "cost_usd": q("SELECT SUM(cost_usd) FROM runs")}

    def last_run(self) -> dict | None:
        with self.conn() as c:
            r = c.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        return dict(r) if r else None
