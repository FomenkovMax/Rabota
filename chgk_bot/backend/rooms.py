"""Комната команды: WebSocket-оркестрация вокруг чистого автомата core.teamgame.
Одна команда — одна комната. Состояние хранится в памяти и снимается в БД на каждом переходе;
таймеры серверные (клиенты получают deadline_ms и server_now_ms и только рисуют отсчёт)."""
import asyncio
import logging
import secrets
import time

from fastapi import WebSocket
from sqlalchemy import select

from core import answers as judge_mod
from core import teamgame as T
from core.models import Game

log = logging.getLogger("backend.rooms")


class Room:
    def __init__(self, team_id: int, settings, factory, questions, stats, llm):
        self.team_id, self.s, self.f = team_id, settings, factory
        self.questions, self.stats, self.llm = questions, stats, llm
        self.game: dict | None = None
        self.game_id: str | None = None
        self.conns: dict[int, WebSocket] = {}
        self.names: dict[int, str] = {}
        self.photos: dict[int, str] = {}
        self.lock = asyncio.Lock()
        self.timer: asyncio.Task | None = None
        self.notice = ""

    # ---------- снимки ----------
    def restore(self) -> None:
        with self.f() as s:
            row = s.scalars(select(Game).where(Game.team_id == self.team_id, Game.status == "active")
                            .order_by(Game.created_at.desc())).first()
            if row:
                self.game, self.game_id = dict(row.state), row.id
                if self.game["phase"] == "judging":    # сервер перезапустился посреди оценки: отдаём спорный случай капитану
                    T.set_verdict(self.game, {"level": "wrong", "score": 0.0, "source": "restart", "disputed": True,
                                              "comment": "Сервер перезапускался, реши сам."}, time.time())

    def save(self) -> None:
        if not self.game:
            return
        with self.f() as s:
            row = s.get(Game, self.game_id)
            if row is None:
                row = Game(id=self.game_id, team_id=self.team_id, mode=self.game["mode"], created_at=time.time())
                s.add(row)
            row.status, row.state, row.updated_at = self.game["status"], dict(self.game), time.time()
            s.commit()

    # ---------- представление для клиентов ----------
    def view(self) -> dict:
        now = time.time()
        g = self.game
        out = {"server_now_ms": int(now * 1000), "notice": self.notice,
               "players": [{"id": u, "name": n, "photo": self.photos.get(u, "")} for u, n in self.names.items() if u in self.conns],
               "game": None}
        if not g:
            return out
        cur = g["current"]
        q = self.questions.get(cur["qid"]) if cur else None
        review = g["phase"] in ("review", "finished")
        v = g["verdict"]
        out["game"] = {
            "mode": g["mode"], "status": g["status"], "phase": g["phase"], "captain_id": g["captain_id"],
            "deadline_ms": int(g["deadline"] * 1000), "idx": g["idx"], "total": g["total"],
            "tour": T.tour_of(g), "score": g["score"], "experts": g["experts"], "viewers": g["viewers"],
            "played": g["played"], "spin": g["spin"] if g["mode"] == T.WHEEL else None,
            "answer": g["answer"], "verdict": v, "think": g["think"],
            "think_now": T.BLITZ_THINK if T.kind_of(g) in T.BLITZ_KINDS else g["think"],
            "question": ({"id": q["id"], "text": q["text"], "media": q.get("media", [])}
                         if q and g["phase"] not in ("finished", "pick") else None),
            "kind": T.kind_of(g), "sub": (cur or {}).get("sub", 0), "of": (cur or {}).get("of", 1),
            "answerer_id": T.answerer_of(g) if cur else None,
            "kinds": g.get("kinds") or [],
            "reveal": ({"answer": q["answer"], "accepted": q.get("accepted", []), "accept_note": q.get("accept_note", ""),
                        "explanation": q.get("explanation", ""), "source": q.get("source", ""), "author": q.get("author", "")}
                       if q and review and g["phase"] == "review" else None),
            "log": g["log"] if g["status"] == "finished" else None,
        }
        return out

    async def broadcast(self) -> None:
        msg = {"type": "state", **self.view()}
        for uid, ws in list(self.conns.items()):
            try:
                await ws.send_json(msg)
            except Exception:
                self.conns.pop(uid, None)

    async def changed(self) -> None:
        self.save()
        self._arm_timer()
        await self.broadcast()

    # ---------- таймеры ----------
    def _arm_timer(self) -> None:
        if self.timer:
            self.timer.cancel()
            self.timer = None
        g = self.game
        if g and g["status"] == "active" and g["phase"] in ("think", "answer") and g["deadline"]:
            self.timer = asyncio.create_task(self._fire(g["phase"], g["idx"], g["deadline"]))

    async def _fire(self, phase: str, idx: int, deadline: float) -> None:
        await asyncio.sleep(max(0.0, deadline - time.time()))
        async with self.lock:
            g = self.game
            if not g or g["phase"] != phase or g["idx"] != idx:    # устарел: игра ушла дальше
                return
            if phase == "think":
                T.to_answer(g, time.time())
            else:
                T.timeout_answer(g, time.time())
            await self.changed()

    # ---------- действия игроков ----------
    async def connect(self, uid: int, name: str, ws: WebSocket, photo: str = "") -> None:
        async with self.lock:
            old = self.conns.get(uid)
            self.conns[uid], self.names[uid], self.photos[uid] = ws, name, photo
            if old and old is not ws:
                try:
                    await old.close()
                except Exception:
                    pass
            if self.game is None:
                self.restore()
                self._arm_timer()
            await self.broadcast()

    async def disconnect(self, uid: int, ws: WebSocket) -> None:
        async with self.lock:
            if self.conns.get(uid) is ws:
                self.conns.pop(uid, None)
                await self.broadcast()

    async def handle(self, uid: int, msg: dict) -> str | None:
        """Возвращает текст ошибки для отправителя или None."""
        kind = msg.get("type")
        is_admin = uid == self.s.admin_id
        async with self.lock:
            self.notice = ""
            g = self.game
            try:
                if kind == "start":
                    if g and g["status"] == "active":
                        raise T.GameError("Игра уже идёт")
                    mode = msg.get("mode", T.SPORT)
                    tours = max(1, min(int(msg.get("tours", 3)), 5))        # границы: иначе per_tour=0 ломает нумерацию туров
                    per_tour = max(1, min(int(msg.get("per_tour", 12)), 20))
                    n = T.wheel.N_SECTORS + T.EXTRA_FOR_SPECIALS if mode == T.WHEEL else tours * per_tour
                    seen = self.stats.seen(self.team_id)
                    hidden = self.stats.hidden_ids(self.s.hide_min_answers, self.s.hide_lo, self.s.hide_hi)
                    qs = self.questions.choose(max(1, min(n, 60)), seen, hidden)
                    self.game = T.new_game(mode, [q["id"] for q in qs], uid, time.time(), think=self.s.think_seconds,
                                           answer=self.s.team_answer_seconds, tours=tours, per_tour=per_tour)
                    self.game_id = secrets.token_hex(8)
                    T.start_round(self.game, time.time())
                elif g is None:
                    raise T.GameError("Игра не начата")
                elif kind == "answer":
                    T.submit(g, uid, str(msg.get("text", "")), time.time())
                    await self.changed()          # показываем «судья думает»
                    await self._judge()
                elif kind == "pick":
                    pid = int(msg["user_id"])
                    if pid not in self.conns:
                        raise T.GameError("Этого игрока нет за столом")
                    T.pick_answerer(g, uid, pid, time.time())
                elif kind == "override":
                    T.override(g, uid, bool(msg.get("correct")))
                elif kind == "next":
                    rec = T.advance(g, uid, time.time())
                    if rec:
                        self.stats.record(self.team_id, rec["qid"], rec["score"] if g["mode"] == T.SPORT else (1.0 if rec["level"] == "correct" else 0.0),
                                          rec["answer"], "team", rec["time_ms"])
                elif kind == "captain":
                    T.set_captain(g, uid, int(msg["user_id"]), is_admin)
                elif kind == "stop":
                    if uid != g["captain_id"] and not is_admin:
                        raise T.GameError("Останавливает капитан или админ")
                    if g["phase"] == "review":
                        T.commit_round(g)
                    T.finish(g)
                else:
                    raise T.GameError("Неизвестная команда")
            except (T.GameError, ValueError, KeyError) as e:
                return str(e) if isinstance(e, T.GameError) else "Некорректный запрос"
            await self.changed()
        return None

    async def _judge(self) -> None:
        """Вызывается под локом: оценка ответа. ИИ-судья с коротким таймаутом, иначе запасной режим и пометка «спорно»."""
        g = self.game
        q = self.questions.get(g["current"]["qid"])
        v = await judge_mod.judge(self.llm, self.s.judge_model, q, g["answer"], timeout=self.s.judge_timeout)
        T.set_verdict(g, {"level": v.level, "score": v.score, "comment": v.comment, "source": v.source, "disputed": v.disputed}, time.time())
