"""Командная игра как чистый конечный автомат: состояние — обычный словарь (хранится в БД как JSON),
время передаётся параметром now, поэтому всё детерминированно тестируется и переживает рестарт сервера.

Фазы: think (обсуждение) -> answer (капитан сдаёт ответ) -> judging -> review (вердикт, капитан может изменить) -> следующий раунд / finished.
Режимы: sport — N туров по M вопросов, очки = взятые вопросы; wheel — 13 секторов, игра до WHEEL_GOAL очков (знатоки/телезрители)."""
import random

from . import wheel

WHEEL_GOAL = 6
SPORT = "sport"
WHEEL = "wheel"


class GameError(Exception):
    pass


def new_game(mode: str, question_ids: list[str], captain_id: int, now: float, *,
             think: int = 60, answer: int = 20, tours: int = 3, per_tour: int = 12) -> dict:
    if mode == WHEEL:
        total = min(wheel.N_SECTORS, len(question_ids))
    elif mode == SPORT:
        total = min(tours * per_tour, len(question_ids))
    else:
        raise GameError("Неизвестный режим")
    if total == 0:
        raise GameError("Нет вопросов")
    return {
        "mode": mode, "status": "active", "phase": "idle", "captain_id": captain_id, "created_at": now,
        "think": think, "answer_secs": answer, "per_tour": per_tour if mode == SPORT else 0,
        "questions": question_ids[:total], "total": total, "idx": -1,
        "score": 0.0, "experts": 0, "viewers": 0, "played": [],
        "current": None, "deadline": 0.0, "round_started": 0.0,
        "answer": None, "answered_by": None, "verdict": None, "log": [], "spin": None,
    }


def start_round(g: dict, now: float, rng: random.Random | None = None) -> None:
    if g["status"] != "active" or g["phase"] not in ("idle", "review"):
        raise GameError("Нельзя начать раунд сейчас")
    if g["mode"] == WHEEL:
        sp = wheel.spin(g["played"], g["total"], rng)
        if sp is None:
            return finish(g)
        g["spin"] = sp
        g["current"] = {"qid": g["questions"][sp["sector"]], "sector": sp["sector"]}
        g["played"].append(sp["sector"])
        g["idx"] += 1
    else:
        g["idx"] += 1
        if g["idx"] >= g["total"]:
            return finish(g)
        g["current"] = {"qid": g["questions"][g["idx"]], "sector": None}
    g["answer"] = g["answered_by"] = g["verdict"] = None
    g["phase"] = "think"
    g["round_started"] = now
    # в волчке сначала крутится стрелка (~6 с), потом идёт минута
    g["deadline"] = now + g["think"] + (6 if g["mode"] == WHEEL else 0)


def to_answer(g: dict, now: float) -> bool:
    """Конец минуты: даём капитану окно на ответ. Идемпотентно."""
    if g["phase"] != "think":
        return False
    g["phase"] = "answer"
    g["deadline"] = now + g["answer_secs"]
    return True


def submit(g: dict, user_id: int, text: str, now: float) -> None:
    if g["phase"] not in ("think", "answer"):
        raise GameError("Сейчас ответ не принимается")
    if user_id != g["captain_id"]:
        raise GameError("Ответ сдаёт только капитан")
    text = text.strip()[:500]
    if not text:
        raise GameError("Пустой ответ")
    g["answer"], g["answered_by"], g["phase"] = text, user_id, "judging"


def timeout_answer(g: dict, now: float) -> bool:
    """Окно ответа закончилось без ответа. Идемпотентно."""
    if g["phase"] != "answer":
        return False
    set_verdict(g, {"level": "wrong", "score": 0.0, "comment": "Время вышло.", "source": "timeout", "disputed": False}, now)
    return True


def set_verdict(g: dict, verdict: dict, now: float) -> None:
    g["verdict"] = {**verdict, "overridden": False}
    g["phase"] = "review"
    g["deadline"] = 0.0
    g["answered_at"] = now


def _points(g: dict, v: dict) -> tuple[float, str]:
    """Сколько очков даёт вердикт: (очки, кому) для волчка 'experts'/'viewers'."""
    if g["mode"] == WHEEL:
        return 1.0, ("experts" if v["level"] == "correct" else "viewers")
    return float(v["score"]), "score"


def _apply(g: dict, v: dict, sign: int) -> None:
    pts, who = _points(g, v)
    if who == "score":
        g["score"] += sign * pts
    else:
        g[who] += sign * int(pts)


def commit_round(g: dict) -> None:
    """Вердикт окончательный: начисляем очки и пишем в журнал. Вызывается один раз при переходе дальше."""
    v = g["verdict"]
    if g["phase"] != "review" or v is None or v.get("committed"):
        return
    _apply(g, v, +1)
    v["committed"] = True
    g["log"].append({"qid": g["current"]["qid"], "sector": g["current"]["sector"], "answer": g["answer"],
                     "level": v["level"], "score": v["score"], "time_ms": int((g.get("answered_at", g["round_started"]) - g["round_started"]) * 1000)})


def override(g: dict, user_id: int, correct: bool) -> None:
    if g["phase"] != "review":
        raise GameError("Менять вердикт можно после ответа")
    if user_id != g["captain_id"]:
        raise GameError("Вердикт меняет только капитан")
    v = g["verdict"]
    v["level"], v["score"] = ("correct", 1.0) if correct else ("wrong", 0.0)
    v["overridden"], v["disputed"] = True, False


def advance(g: dict, user_id: int, now: float, rng: random.Random | None = None) -> dict | None:
    """Капитан жмёт «дальше»: фиксируем вопрос и начинаем следующий (или завершаем). Возвращает запись журнала."""
    if user_id != g["captain_id"]:
        raise GameError("Дальше двигает капитан")
    if g["phase"] != "review":
        raise GameError("Сначала нужно закончить вопрос")
    commit_round(g)
    rec = g["log"][-1]
    wheel_over = g["mode"] == WHEEL and (g["experts"] >= WHEEL_GOAL or g["viewers"] >= WHEEL_GOAL or len(g["played"]) >= g["total"])
    if wheel_over:
        finish(g)
    elif g["mode"] == SPORT and g["idx"] + 1 >= g["total"]:
        finish(g)
    else:
        start_round(g, now, rng)
    return rec


def finish(g: dict) -> None:
    g["status"], g["phase"], g["deadline"] = "finished", "finished", 0.0


def set_captain(g: dict, by: int, new_id: int, is_admin: bool) -> None:
    if by != g["captain_id"] and not is_admin:
        raise GameError("Капитана меняет капитан или админ")
    g["captain_id"] = new_id


def tour_of(g: dict) -> tuple[int, int] | None:
    if g["mode"] != SPORT or g["idx"] < 0:
        return None
    return g["idx"] // g["per_tour"] + 1, g["idx"] % g["per_tour"] + 1
