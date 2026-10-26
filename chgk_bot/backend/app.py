"""FastAPI-приложение Mini App. Э1: авторизация и соло-режим с серверным таймером."""
import logging
import secrets
import time
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Response, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from core import answers as judge_mod
from core.brand import load_brand
from core.db import make_session_factory
from core.llm import make_client
from core.models import SoloRound
from core.qimport import parse as parse_import
from core.repo import QuestionRepo, StatsRepo, UserRepo
from core.card import render_card
from core.statsq import actor_stats, team_extra
from core.seasons import check_achievements, season_overview
from core.steps import make_steps

from .access import AccessChecker
from .rooms import Room
from .auth import AuthError, create_token, decode_token, validate_init_data
from .settings import Settings


log = logging.getLogger("backend.app")


class InitIn(BaseModel):
    init_data: str


class DevIn(BaseModel):
    id: int
    name: str = "Dev"


class AnswerIn(BaseModel):
    round_id: str
    answer: str


class QuestionIn(BaseModel):
    text: str
    answer: str
    explanation: str
    accepted: list[str] = []
    rejected: list[str] = []
    accept_note: str = ""
    source: str = ""
    author: str = ""
    tags: list[str] = []
    difficulty: int = 3


class ImportIn(BaseModel):
    format: str
    content: str
    dry_run: bool = False


class HiddenIn(BaseModel):
    hidden: bool


class RoundIn(BaseModel):
    round_id: str


def public_question(q: dict) -> dict:
    """То, что видит игрок ДО ответа: без ответа и разбора."""
    return {"id": q["id"], "text": q["text"], "media": q.get("media", []), "author": q.get("author", ""),
            "difficulty": q.get("difficulty")}


def reveal(q: dict) -> dict:
    return {"answer": q["answer"], "accepted": q.get("accepted", []), "accept_note": q.get("accept_note", ""),
            "explanation": q.get("explanation", ""), "author": q.get("author", ""),
            "source": q.get("source", ""), "url": q.get("url", "")}


def create_app(settings: Settings, factory=None, llm_client=None, http: httpx.AsyncClient | None = None) -> FastAPI:
    factory = factory or make_session_factory(settings.database_url)
    questions, stats, users = QuestionRepo(factory), StatsRepo(factory), UserRepo(factory)
    access = AccessChecker(settings, http)
    brand = load_brand(settings.brand_file)
    if llm_client is None and settings.anthropic_key:
        llm_client = make_client(settings.anthropic_key, settings.anthropic_auth_mode)
    steps_model = settings.steps_model or settings.judge_model

    app = FastAPI(title="ЧГК-тренажёр", docs_url=None, redoc_url=None)
    app.state.factory = factory

    async def current_user(authorization: str = Header(default="")) -> dict:
        token = authorization.removeprefix("Bearer ").strip()
        try:
            user = decode_token(token, settings.jwt_secret)
        except AuthError as e:
            raise HTTPException(401, str(e))
        if not await access.allowed(user["id"]):
            raise HTTPException(403, "Игра только для участников команды")
        return user

    def issue(uid: int, name: str, username: str | None, photo: str = "") -> dict:
        users.touch(uid, name, username, photo or None)
        return {"token": create_token(uid, name, settings.jwt_secret, settings.token_ttl, photo=photo),
                "user": {"id": uid, "name": name, "photo": photo}}

    @app.get("/api/health")
    def health():
        return {"ok": True, "questions": questions.count()}

    @app.post("/api/auth/telegram")
    async def auth_telegram(body: InitIn):
        try:
            data = validate_init_data(body.init_data, settings.bot_token, settings.init_data_max_age)
        except AuthError as e:
            raise HTTPException(401, str(e))
        u = data["user"]
        uid = int(u["id"])
        if not await access.allowed(uid):
            raise HTTPException(403, "Игра только для участников команды")
        name = " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x) or u.get("username") or str(uid)
        photo = str(u.get("photo_url") or "")
        photo = photo if photo.startswith("https://") and len(photo) < 500 else ""   # только https-ссылки Telegram
        return issue(uid, name, u.get("username"), photo)

    if settings.dev_auth:
        @app.post("/api/auth/dev")
        def auth_dev(body: DevIn):
            return issue(body.id, body.name, None)

    @app.get("/api/me")
    def me(user: dict = Depends(current_user)):
        return {"user": user, "is_admin": user["id"] == settings.admin_id, "stats": stats.summary(user["id"]), "brand": brand,
                "think_seconds": settings.think_seconds}

    def _hidden() -> set[str]:
        return stats.hidden_ids(settings.hide_min_answers, settings.hide_lo, settings.hide_hi)

    @app.post("/api/solo/next")
    def solo_next(user: dict = Depends(current_user)):
        q, left = questions.pick(stats.seen(user["id"]), _hidden())
        if q is None:
            raise HTTPException(404, "Вопросов пока нет")
        now = time.time()
        rid = secrets.token_hex(8)
        with factory() as s:
            s.add(SoloRound(id=rid, user_id=user["id"], question_id=q["id"], started_at=now,
                            deadline_at=now + settings.think_seconds))
            s.commit()
        return {"round_id": rid, "question": public_question(q), "fresh_left": left,
                "think_seconds": settings.think_seconds,
                "server_now_ms": int(now * 1000), "deadline_ms": int((now + settings.think_seconds) * 1000)}

    def _open_round(rid: str, uid: int) -> tuple[SoloRound, dict]:
        with factory() as s:
            r = s.get(SoloRound, rid)
            if r is None or r.user_id != uid:
                raise HTTPException(404, "Раунд не найден")
            if r.finished_at is not None:
                raise HTTPException(409, "Раунд уже завершён")
            q = questions.get(r.question_id)
            if q is None:
                raise HTTPException(404, "Вопрос удалён")
            return r, q

    def _finish(rid: str) -> None:
        with factory() as s:
            r = s.get(SoloRound, rid)
            r.finished_at = time.time()
            s.commit()

    @app.post("/api/solo/answer")
    async def solo_answer(body: AnswerIn, user: dict = Depends(current_user)):
        r, q = _open_round(body.round_id, user["id"])
        now = time.time()
        if now > r.deadline_at + settings.answer_grace_seconds:
            # время вышло: засчитываем неответ
            _finish(r.id)
            stats.record(user["id"], q["id"], 0.0, None, "solo", int((now - r.started_at) * 1000))
            return {"timeout": True, "verdict": {"level": "wrong", "score": 0.0, "comment": "Время вышло.",
                                                 "source": "timeout", "disputed": False}, "reveal": reveal(q)}
        text = body.answer.strip()[:500]
        v = await judge_mod.judge(llm_client, settings.judge_model, q, text, timeout=settings.judge_timeout)
        _finish(r.id)
        stats.record(user["id"], q["id"], v.score, text, "solo", int((now - r.started_at) * 1000))
        return {"timeout": False, "verdict": {"level": v.level, "score": v.score, "comment": v.comment,
                                               "source": v.source, "disputed": v.disputed},
                "reveal": reveal(q), "stats": stats.summary(user["id"]), "new_achievements": _new_ach(user["id"])}

    @app.post("/api/solo/skip")
    def solo_skip(body: RoundIn, user: dict = Depends(current_user)):
        r, q = _open_round(body.round_id, user["id"])
        _finish(r.id)
        stats.record(user["id"], q["id"], 0.0, None, "solo", int((time.time() - r.started_at) * 1000))
        return {"reveal": reveal(q), "stats": stats.summary(user["id"])}

    @app.post("/api/questions/{qid}/steps")
    async def question_steps(qid: str, user: dict = Depends(current_user)):
        if qid not in stats.seen(user["id"]):
            raise HTTPException(403, "Разбор доступен после ответа на вопрос")
        q = questions.get(qid)
        if q is None:
            raise HTTPException(404, "Вопрос не найден")
        data = q.get("steps")
        if not data and llm_client is not None:
            data = await make_steps(llm_client, steps_model, q)
            if data:
                questions.set_steps(qid, data)
        return {"steps": data}

    def _new_ach(uid: int) -> list[dict]:
        return [{"code": c, **brand["achievements"][c]} for c in check_achievements(factory, uid, brand)]

    @app.get("/api/season")
    def season(user: dict = Depends(current_user)):
        _new_ach(user["id"])     # ачивки за командные игры выдаём при просмотре сезона
        return season_overview(factory, brand, user["id"])

    # ---------- админка вопросов (только ADMIN_ID) ----------
    async def admin_user(user: dict = Depends(current_user)) -> dict:
        if not settings.admin_id or user["id"] != settings.admin_id:
            raise HTTPException(403, "Только для администратора")
        return user

    @app.get("/api/admin/questions")
    def admin_list(q: str = "", hidden: bool | None = None, offset: int = 0, limit: int = 30, _: dict = Depends(admin_user)):
        total, items = questions.search(q, hidden, min(limit, 100), max(0, offset))
        rates = stats.question_rates()
        for it in items:
            n, k = rates.get(it["id"], (0, 0))
            it["answered"], it["taken"] = n, k
        return {"total": total, "items": items}

    @app.get("/api/admin/questions/{qid}")
    def admin_get(qid: str, _: dict = Depends(admin_user)):
        d = questions.get_full(qid)
        if d is None:
            raise HTTPException(404, "Нет такого вопроса")
        return d

    @app.post("/api/admin/questions")
    def admin_add(body: QuestionIn, _: dict = Depends(admin_user)):
        if not all(x.strip() for x in (body.text, body.answer, body.explanation)):
            raise HTTPException(422, "Нужны текст, ответ и разбор")
        d = body.model_dump()
        d["origin"] = "admin"
        if not questions.add([d]):
            raise HTTPException(409, "Такой вопрос уже есть")
        return {"ok": True}

    @app.put("/api/admin/questions/{qid}")
    def admin_edit(qid: str, body: QuestionIn, _: dict = Depends(admin_user)):
        if not questions.edit(qid, body.model_dump()):
            raise HTTPException(404, "Вопрос не найден или не заполнены обязательные поля")
        return {"ok": True}

    @app.post("/api/admin/questions/{qid}/hidden")
    def admin_hidden(qid: str, body: HiddenIn, _: dict = Depends(admin_user)):
        if not questions.set_hidden(qid, body.hidden):
            raise HTTPException(404, "Вопрос не найден")
        return {"ok": True}

    @app.delete("/api/admin/questions/{qid}")
    def admin_delete(qid: str, _: dict = Depends(admin_user)):
        if not questions.delete(qid):
            raise HTTPException(404, "Вопрос не найден")
        return {"ok": True}

    @app.post("/api/admin/import")
    def admin_import(body: ImportIn, _: dict = Depends(admin_user)):
        items, errors = parse_import(body.format, body.content)
        for it in items:
            it.setdefault("origin", "import")
        added = 0 if body.dry_run else questions.add(items)
        return {"valid": len(items), "added": added, "duplicates": 0 if body.dry_run else len(items) - added,
                "errors": errors[:50], "dry_run": body.dry_run, "total_in_db": questions.count()}

    # одна команда: id чата первой разрешённой группы (отрицательный, как в статистике бота) или -1
    team_id = next(iter(sorted(settings.allowed_chats)), -1)

    # ---------- статистика ----------
    @app.get("/api/stats/me")
    def stats_me(user: dict = Depends(current_user)):
        return actor_stats(factory, user["id"])

    @app.get("/api/stats/team")
    def stats_team(user: dict = Depends(current_user)):
        return {**actor_stats(factory, team_id), **team_extra(factory, team_id)}

    def _card(scope: str, user: dict) -> bytes:
        if scope == "team":
            return render_card("Команда", "тренировка знатоков", actor_stats(factory, team_id))
        return render_card(user["name"], "личная статистика", actor_stats(factory, user["id"]))

    @app.get("/api/stats/card.png")
    def stats_card(scope: str = "me", user: dict = Depends(current_user)):
        return Response(_card(scope, user), media_type="image/png")

    @app.post("/api/stats/card/send")
    async def stats_card_send(scope: str = "me", user: dict = Depends(current_user)):
        """Отправляет карточку в личку игрока ботом — оттуда её можно переслать в чат команды."""
        png = _card(scope, user)
        r = await access.http.post(f"https://api.telegram.org/bot{settings.bot_token}/sendPhoto",
                                   data={"chat_id": user["id"]}, files={"photo": ("card.png", png, "image/png")})
        if r.status_code != 200:
            raise HTTPException(502, "Не удалось отправить карточку: сначала напиши боту /start")
        return {"ok": True}

    # ---------- командная игра (WebSocket) ----------
    room = Room(team_id, settings, factory, questions, stats, llm_client)
    app.state.room = room

    @app.websocket("/api/ws")
    async def ws_team(ws: WebSocket, token: str = ""):
        try:
            user = decode_token(token, settings.jwt_secret)
        except AuthError:
            await ws.close(code=4401)
            return
        if not await access.allowed(user["id"]):
            await ws.close(code=4403)
            return
        await ws.accept()
        await room.connect(user["id"], user["name"], ws, user.get("photo", ""))
        try:
            while True:
                msg = await ws.receive_json()
                err = await room.handle(user["id"], msg)
                if err:
                    await ws.send_json({"type": "error", "message": err})
        except WebSocketDisconnect:
            pass
        except Exception:
            log.exception("ws error")
        finally:
            await room.disconnect(user["id"], ws)

    dist = Path(__file__).resolve().parent.parent / "webapp" / "dist"
    if dist.exists() and not settings.public_host:   # без Caddy (локальная разработка) отдаём фронт сами
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    return app
