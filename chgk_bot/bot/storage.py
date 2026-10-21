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

    def count(self) -> int:
        return len(self.items)

    def get(self, qid: str) -> dict | None:
        return next((q for q in self.items if q["id"] == qid), None)

    def set_steps(self, qid: str, steps: dict) -> None:
        """Сохраняет разбор по шагам рядом с вопросом (кэш, чтобы не просить модель повторно)."""
        for q in self.items:
            if q["id"] == qid:
                q["steps"] = steps
                self._save()
                return

    def pick(self, seen: set[str], exclude: frozenset | set = frozenset()) -> tuple[dict | None, int]:
        """Случайный ещё не виденный вопрос и сколько таких осталось (включая его).
        exclude — скрытые вопросы (слишком лёгкие/сложные по статистике). Когда всё пройдено — берём любой (повтор)."""
        pool = [q for q in self.items if q["id"] not in exclude] or self.items
        fresh = [q for q in pool if q["id"] not in seen]
        if fresh:
            return random.choice(fresh), len(fresh)
        return (random.choice(pool), 0) if pool else (None, 0)

    def choose(self, n: int, seen: set[str], exclude: frozenset | set = frozenset()) -> list[dict]:
        """n разных вопросов для командной игры: сначала не игранные командой, затем (если мало) остальные."""
        pool = [q for q in self.items if q["id"] not in exclude] or list(self.items)
        fresh = [q for q in pool if q["id"] not in seen]
        random.shuffle(fresh)
        out = fresh[:n]
        if len(out) < n:
            rest = [q for q in pool if q not in out]
            random.shuffle(rest)
            out += rest[: n - len(out)]
        return out


class Stats:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS results ("
            "user_id INTEGER, qid TEXT, score REAL, answer TEXT, ts REAL)"
        )
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(results)")}
        if "mode" not in cols:  # миграция: solo / team
            self.db.execute("ALTER TABLE results ADD COLUMN mode TEXT DEFAULT 'solo'")
        self.db.commit()

    def record(self, user_id: int, qid: str, score: float, answer: str | None, mode: str = "solo") -> None:
        """user_id: в соло — id игрока, в командной игре — id чата (отрицательное число)."""
        self.db.execute(
            "INSERT INTO results (user_id, qid, score, answer, ts, mode) VALUES (?,?,?,?,?,?)",
            (user_id, qid, score, answer, time.time(), mode),
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

    # --- статистика по вопросам: «доля взявших» считается по ПЕРВОЙ попытке каждого игрока/команды ---
    _FIRST = (
        "SELECT r.qid, r.user_id, r.score FROM results r "
        "WHERE r.ts = (SELECT MIN(ts) FROM results WHERE user_id=r.user_id AND qid=r.qid)"
    )

    def question_rates(self) -> dict[str, tuple[int, int]]:
        """qid -> (сколько игроков/команд ответило, сколько взяло: score == 1)."""
        agg: dict[str, tuple[int, int]] = {}
        for qid, _user, score in self.db.execute(self._FIRST):
            n, k = agg.get(qid, (0, 0))
            agg[qid] = (n + 1, k + (1 if score >= 1 else 0))
        return agg

    def rate(self, qid: str) -> tuple[int, float | None]:
        """(число ответивших, доля взявших 0..1 или None, если ответов нет)."""
        n, k = self.question_rates().get(qid, (0, 0))
        return n, (k / n if n else None)

    def hidden_ids(self, min_n: int = 6, lo: float = 0.10, hi: float = 0.90) -> set[str]:
        """Вопросы, которые при достаточной выборке берут почти все (> hi) или почти никто (< lo)."""
        return {
            qid for qid, (n, k) in self.question_rates().items()
            if n >= min_n and not (lo <= k / n <= hi)
        }
