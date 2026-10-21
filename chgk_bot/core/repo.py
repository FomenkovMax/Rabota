"""Репозитории над PostgreSQL: тот же интерфейс, что у JSON/SQLite-классов MVP (bot/storage.py),
поэтому бот переключается на общую БД сменой одной переменной (DATABASE_URL)."""
import hashlib
import random
import time

from sqlalchemy import case, delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from .models import Attempt, Question, User

REQUIRED = ("text", "answer", "explanation")


def make_id(text: str) -> str:
    return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:8]


def question_to_dict(q: Question) -> dict:
    """Строка БД -> словарь в формате MVP (его ждут бот, судья и «разбор по шагам»)."""
    ex = q.extra or {}
    d = {
        "id": q.id, "text": q.text, "answer": q.answer,
        "accepted": list(q.accepted or []), "rejected": list(q.rejected or []),
        "accept_note": q.accept_note or "", "explanation": q.comment or "",
        "author": q.author or "", "source": q.source or "", "pack_title": q.pack or "", "url": q.url or "",
        "difficulty": q.difficulty, "origin": q.origin or "", "media": list(q.media or []),
        "tags": ex.get("tags") or ([q.topic] if q.topic else []),
    }
    if q.steps:
        d["steps"] = q.steps
    for k in ("facts", "chgk", "pattern"):
        if k in ex:
            d[k] = ex[k]
    return d


def _fields(d: dict) -> dict:
    """Словарь MVP -> поля таблицы questions."""
    tags = list(d.get("tags") or [])
    extra = {"tags": tags}
    for k in ("facts", "chgk", "pattern"):
        if d.get(k) is not None:
            extra[k] = d[k]
    return dict(
        text=d["text"], answer=str(d["answer"]), accepted=list(d.get("accepted") or []),
        rejected=list(d.get("rejected") or []), accept_note=d.get("accept_note") or "",
        comment=d["explanation"], source=d.get("source") or "", author=d.get("author") or "",
        pack=d.get("pack_title") or "", url=d.get("url") or "", topic=(tags[0] if tags else "")[:100],
        difficulty=int(d.get("difficulty") or 3), media=list(d.get("media") or []),
        origin=d.get("origin") or "", extra=extra,
    )


class QuestionRepo:
    def __init__(self, factory: sessionmaker[Session]):
        self.f = factory

    def count(self) -> int:
        with self.f() as s:
            return s.scalar(select(func.count()).select_from(Question)) or 0

    def get(self, qid: str) -> dict | None:
        with self.f() as s:
            q = s.get(Question, qid)
            return question_to_dict(q) if q else None

    def _visible_ids(self, s: Session, exclude) -> list[str]:
        ids = set(s.scalars(select(Question.id).where(Question.hidden.is_(False))))
        pool = ids - set(exclude)
        return sorted(pool or ids)   # если всё скрыто — берём всё, чем остаться без вопросов

    def add(self, new: list[dict], update: bool = False) -> int:
        """Добавляет вопросы, пропуская дубли и неполные. update=True — обновляет существующие
        (кэш «разбора по шагам» и флаг hidden сохраняются). Возвращает число добавленных."""
        added = 0
        with self.f() as s:
            for d in new:
                if not all(str(d.get(k, "")).strip() for k in REQUIRED):
                    continue
                qid = make_id(d["text"])
                fields = _fields(d)
                row = s.get(Question, qid)
                if row is None:
                    s.add(Question(id=qid, created_at=time.time(), steps=d.get("steps"), **fields))
                    s.flush()
                    added += 1
                elif update:
                    for k, v in fields.items():
                        setattr(row, k, v)
                    if d.get("steps"):
                        row.steps = d["steps"]
            s.commit()
        return added

    # --- админка ---
    def search(self, query: str = "", hidden: bool | None = None, limit: int = 30, offset: int = 0) -> tuple[int, list[dict]]:
        """Список для админки: (всего найдено, страница). Поиск по тексту/ответу делаем в Python (в SQLite lower() не знает кириллицу)."""
        q = query.strip().lower()
        with self.f() as s:
            stmt = select(Question).order_by(Question.created_at.desc(), Question.id)
            if hidden is not None:
                stmt = stmt.where(Question.hidden.is_(hidden))
            rows = [r for r in s.scalars(stmt) if not q or q in r.text.lower() or q in str(r.answer).lower()]
            page = rows[offset: offset + limit]
            return len(rows), [{"id": r.id, "text": r.text[:140], "answer": r.answer, "hidden": r.hidden,
                                "source": r.source, "pack": r.pack} for r in page]

    def get_full(self, qid: str) -> dict | None:
        with self.f() as s:
            q = s.get(Question, qid)
            if not q:
                return None
            d = question_to_dict(q)
            d["hidden"] = q.hidden
            return d

    def edit(self, qid: str, d: dict) -> bool:
        """Правка вопроса по id (id не меняется, чтобы не потерять статистику, даже если текст изменён)."""
        if not all(str(d.get(k, "")).strip() for k in REQUIRED):
            return False
        with self.f() as s:
            row = s.get(Question, qid)
            if row is None:
                return False
            for k, v in _fields(d).items():
                setattr(row, k, v)
            row.steps = None            # текст изменился — прежний разбор по шагам устарел
            s.commit()
            return True

    def set_hidden(self, qid: str, hidden: bool) -> bool:
        with self.f() as s:
            row = s.get(Question, qid)
            if row is None:
                return False
            row.hidden = hidden
            s.commit()
            return True

    def delete(self, qid: str) -> bool:
        with self.f() as s:
            n = s.execute(delete(Question).where(Question.id == qid)).rowcount
            s.commit()
            return bool(n)

    def set_steps(self, qid: str, steps: dict) -> None:
        with self.f() as s:
            q = s.get(Question, qid)
            if q:
                q.steps = steps
                s.commit()

    def remove_answers(self, answers: list[str]) -> int:
        """Удаляет вопросы по точному ответу (регистр не важен; сравниваем в Python: lower() в SQLite не знает кириллицу)."""
        wanted = {a.strip().lower() for a in answers}
        with self.f() as s:
            ids = [i for i, a in s.execute(select(Question.id, Question.answer)) if str(a).strip().lower() in wanted]
            if ids:
                s.execute(delete(Question).where(Question.id.in_(ids)))
                s.commit()
            return len(ids)

    def pick(self, seen: set[str], exclude=frozenset()) -> tuple[dict | None, int]:
        """Случайный ещё не виденный вопрос и сколько таких осталось (включая его); когда всё пройдено — повтор."""
        with self.f() as s:
            pool = self._visible_ids(s, exclude)
            if not pool:
                return None, 0
            fresh = [i for i in pool if i not in seen]
            qid = random.choice(fresh or pool)
            return question_to_dict(s.get(Question, qid)), len(fresh)

    def choose(self, n: int, seen: set[str], exclude=frozenset()) -> list[dict]:
        """n разных вопросов для командной игры: сначала не игранные, затем (если мало) остальные."""
        with self.f() as s:
            pool = self._visible_ids(s, exclude)
            fresh = [i for i in pool if i not in seen]
            random.shuffle(fresh)
            out = fresh[:n]
            if len(out) < n:
                rest = [i for i in pool if i not in out]
                random.shuffle(rest)
                out += rest[: n - len(out)]
            rows = {q.id: q for q in s.scalars(select(Question).where(Question.id.in_(out)))}
            return [question_to_dict(rows[i]) for i in out]


class StatsRepo:
    def __init__(self, factory: sessionmaker[Session]):
        self.f = factory

    def record(self, user_id: int, qid: str, score: float, answer: str | None,
               mode: str = "solo", time_ms: int | None = None) -> None:
        with self.f() as s:
            s.add(Attempt(actor_id=user_id, question_id=qid, score=score, answer=answer,
                          mode=mode, time_ms=time_ms, ts=time.time()))
            s.commit()

    def seen(self, user_id: int) -> set[str]:
        with self.f() as s:
            return set(s.scalars(select(Attempt.question_id).where(Attempt.actor_id == user_id).distinct()))

    def summary(self, user_id: int) -> dict:
        with self.f() as s:
            row = s.execute(
                select(
                    func.count(), func.coalesce(func.sum(Attempt.score), 0),
                    func.coalesce(func.sum(case((Attempt.score == 1, 1), else_=0)), 0),
                    func.coalesce(func.sum(case((Attempt.score == 0.5, 1), else_=0)), 0),
                ).where(Attempt.actor_id == user_id)
            ).one()
        return {"played": row[0], "points": float(row[1]), "correct": int(row[2]), "close": int(row[3])}

    # --- «доля взявших» по ПЕРВОЙ попытке каждого игрока/команды ---
    @staticmethod
    def _first_attempts(qid: str | None = None):
        rn = func.row_number().over(
            partition_by=(Attempt.actor_id, Attempt.question_id), order_by=(Attempt.ts, Attempt.id)
        ).label("rn")
        inner = select(Attempt.question_id.label("qid"), Attempt.actor_id.label("actor"),
                       Attempt.score.label("score"), rn)
        if qid is not None:
            inner = inner.where(Attempt.question_id == qid)
        sub = inner.subquery()
        return select(sub.c.qid, sub.c.actor, sub.c.score).where(sub.c.rn == 1)

    def question_rates(self) -> dict[str, tuple[int, int]]:
        """qid -> (сколько игроков/команд ответило, сколько взяло: score == 1)."""
        agg: dict[str, tuple[int, int]] = {}
        with self.f() as s:
            for qid, _actor, score in s.execute(self._first_attempts()):
                n, k = agg.get(qid, (0, 0))
                agg[qid] = (n + 1, k + (1 if score >= 1 else 0))
        return agg

    def rate(self, qid: str) -> tuple[int, float | None]:
        n = k = 0
        with self.f() as s:
            for _qid, _actor, score in s.execute(self._first_attempts(qid)):
                n, k = n + 1, k + (1 if score >= 1 else 0)
        return n, (k / n if n else None)

    def hidden_ids(self, min_n: int = 6, lo: float = 0.10, hi: float = 0.90) -> set[str]:
        return {qid for qid, (n, k) in self.question_rates().items() if n >= min_n and not (lo <= k / n <= hi)}


class UserRepo:
    def __init__(self, factory: sessionmaker[Session]):
        self.f = factory

    def touch(self, tg_id: int, name: str, username: str | None) -> None:
        """Создаёт игрока при первом входе и обновляет имя/время последнего визита."""
        with self.f() as s:
            u = s.get(User, tg_id)
            if u is None:
                s.add(User(tg_id=tg_id, name=name, username=username))
            else:
                u.name, u.username, u.last_seen = name, username, time.time()
            s.commit()
