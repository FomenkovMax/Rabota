"""База вопросов (JSON) и статистика игроков (SQLite)."""
import hashlib
import json
import random
import shutil
import sqlite3
import time
from pathlib import Path

REQUIRED = ("text", "answer", "explanation")


def make_id(text: str) -> str:
    return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:8]


class QuestionBank:
    def __init__(self, path: Path, seed: Path | None = None):
        self.path = path
        if not path.exists() and seed and seed.exists():
            shutil.copy(seed, path)
        self.items: list[dict] = []
        self.reload()

    def reload(self) -> None:
        if self.path.exists():
            self.items = json.loads(self.path.read_text(encoding="utf-8"))
            for q in self.items:  # id считаем по тексту, чтобы можно было править JSON руками
                q.setdefault("id", make_id(q["text"]))
                q.setdefault("accepted", [])
        else:
            self.items = []

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.items, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def remove_answers(self, answers: list[str]) -> int:
        """Удаляет вопросы по точному ответу (регистр не важен). Возвращает число удалённых."""
        wanted = {a.strip().lower() for a in answers}
        keep = [q for q in self.items if str(q["answer"]).strip().lower() not in wanted]
        removed = len(self.items) - len(keep)
        if removed:
            self.items = keep
            self._save()
        return removed

    def add(self, new: list[dict], update: bool = False) -> int:
        """Добавляет вопросы, пропуская дубли и неполные. update=True — заменяет уже существующие (по тексту).
        Возвращает число добавленных."""
        known = {q["id"] for q in self.items}
        added = 0
        changed = False
        for q in new:
            if not all(str(q.get(k, "")).strip() for k in REQUIRED):
                continue
            q = dict(q)
            q["id"] = make_id(q["text"])
            q.setdefault("accepted", [])
            q.setdefault("tags", [])
            q.setdefault("difficulty", 3)
            if q["id"] in known:
                if update:
                    self.items = [q if x["id"] == q["id"] else x for x in self.items]
                    changed = True
                continue
            known.add(q["id"])
            self.items.append(q)
            added += 1
        if added or changed:
            self._save()
        return added

    def get(self, qid: str) -> dict | None:
        return next((q for q in self.items if q["id"] == qid), None)

    def pick(self, seen: set[str]) -> tuple[dict | None, int]:
        """Случайный ещё не виденный вопрос и сколько таких осталось (включая его).
        Когда всё пройдено — берём любой (повтор)."""
        fresh = [q for q in self.items if q["id"] not in seen]
        if fresh:
            return random.choice(fresh), len(fresh)
        return (random.choice(self.items), 0) if self.items else (None, 0)


class Stats:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS results ("
            "user_id INTEGER, qid TEXT, score REAL, answer TEXT, ts REAL)"
        )
        self.db.commit()

    def record(self, user_id: int, qid: str, score: float, answer: str | None) -> None:
        self.db.execute(
            "INSERT INTO results VALUES (?,?,?,?,?)", (user_id, qid, score, answer, time.time())
        )
        self.db.commit()

    def seen(self, user_id: int) -> set[str]:
        rows = self.db.execute("SELECT DISTINCT qid FROM results WHERE user_id=?", (user_id,))
        return {r[0] for r in rows}

    def summary(self, user_id: int) -> dict:
        row = self.db.execute(
            "SELECT COUNT(*), COALESCE(SUM(score),0),"
            " COALESCE(SUM(score=1),0), COALESCE(SUM(score=0.5),0) "
            "FROM results WHERE user_id=?",
            (user_id,),
        ).fetchone()
        return {"played": row[0], "points": row[1], "correct": row[2], "close": row[3]}
