"""Командная игра как чистый конечный автомат: состояние — обычный словарь (хранится в БД как JSON),
время передаётся параметром now, поэтому всё детерминированно тестируется и переживает рестарт сервера.

Фазы: think (обсуждение) -> answer (капитан сдаёт ответ) -> judging -> review (вердикт, капитан может изменить) -> следующий раунд / finished.
Режимы: sport — N туров по M вопросов, очки = взятые вопросы; wheel — 13 секторов, игра до WHEEL_GOAL очков (знатоки/телезрители).

Особые секторы волчка (как в телеигре): один «Блиц» и один «Суперблиц».
- Блиц: три вопроса подряд по 20 секунд обсуждения; очко знатокам — только если взяты все три,
  при первой ошибке раунд заканчивается и очко уходит телезрителям.
- Суперблиц: то же, но отвечает один знаток (его выбирает капитан), команда не помогает."""
import random

from . import wheel

WHEEL_GOAL = 6
SPORT = "sport"
WHEEL = "wheel"
BLITZ, SUPERBLITZ = "blitz", "superblitz"
BLITZ_KINDS = (BLITZ, SUPERBLITZ)
BLITZ_QUESTIONS = 3
BLITZ_THINK = 20          # секунд обсуждения на вопрос блица
SPIN_DELAY = 6            # пока крутится стрелка
EXTRA_FOR_SPECIALS = 2 * (BLITZ_QUESTIONS - 1)   # дополнительные вопросы для блица и суперблица


class GameError(Exception):
    pass


def new_game(mode: str, question_ids: list[str], captain_id: int, now: float, *,
             think: int = 60, answer: int = 20, tours: int = 3, per_tour: int = 12,
             rng: random.Random | None = None) -> dict:
    kinds: list[str] = []
    blitz_q: dict[str, list[str]] = {}
    if mode == WHEEL:
        total = min(wheel.N_SECTORS, len(question_ids))
        kinds = ["normal"] * total
        extra = question_ids[total:total + EXTRA_FOR_SPECIALS]
        # особые секторы — только если хватает вопросов (иначе обычный волчок)
        if total >= 3 and len(extra) == EXTRA_FOR_SPECIALS:
            b, sb = (rng or random).sample(range(total), 2)
            kinds[b], kinds[sb] = BLITZ, SUPERBLITZ
            blitz_q = {str(b): [question_ids[b], extra[0], extra[1]], str(sb): [question_ids[sb], extra[2], extra[3]]}
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
        "kinds": kinds, "blitz_q": blitz_q,
    }


def kind_of(g: dict) -> str:
    cur = g.get("current") or {}
    return cur.get("kind", "normal")


def start_round(g: dict, now: float, rng: random.Random | None = None) -> None:
    if g["status"] != "active" or g["phase"] not in ("idle", "review"):
        raise GameError("Нельзя начать раунд сейчас")
    if g["mode"] == WHEEL:
        sp = wheel.spin(g["played"], g["total"], rng)
        if sp is None:
            return finish(g)
        g["spin"] = sp
        sector = sp["sector"]
        kind = (g.get("kinds") or [])[sector] if sector < len(g.get("kinds") or []) else "normal"
        g["current"] = {"qid": g["questions"][sector], "sector": sector, "kind": kind,
                        "sub": 0, "of": BLITZ_QUESTIONS if kind in BLITZ_KINDS else 1, "answerer": None}
        g["played"].append(sector)
        g["idx"] += 1
    else:
        g["idx"] += 1
        if g["idx"] >= g["total"]:
            return finish(g)
        g["current"] = {"qid": g["questions"][g["idx"]], "sector": None}
    g["answer"] = g["answered_by"] = g["verdict"] = None
    g["round_started"] = now
    if kind_of(g) == SUPERBLITZ:
        g["phase"], g["deadline"] = "pick", 0.0      # сначала капитан выбирает, кто играет суперблиц
        return
    g["phase"] = "think"
    # в волчке сначала крутится стрелка (~6 с), потом идёт обсуждение
    think = BLITZ_THINK if kind_of(g) in BLITZ_KINDS else g["think"]
    g["deadline"] = now + think + (SPIN_DELAY if g["mode"] == WHEEL else 0)


def pick_answerer(g: dict, by: int, user_id: int, now: float) -> None:
    """Суперблиц: капитан выбирает знатока, который будет отвечать один."""
    if g["phase"] != "pick":
        raise GameError("Сейчас некого выбирать")
    if by != g["captain_id"]:
        raise GameError("Игрока для суперблица выбирает капитан")
    g["current"]["answerer"] = int(user_id)
    g["phase"], g["round_started"] = "think", now
    g["deadline"] = now + BLITZ_THINK


def answerer_of(g: dict) -> int:
    """Кто сдаёт ответ: в суперблице — выбранный знаток, иначе капитан."""
    cur = g.get("current") or {}
    if kind_of(g) == SUPERBLITZ and cur.get("answerer"):
        return cur["answerer"]
    return g["captain_id"]


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
    if user_id != answerer_of(g):
        raise GameError("В суперблице отвечает выбранный знаток" if kind_of(g) == SUPERBLITZ else "Ответ сдаёт только капитан")
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


def _apply(g: dict, v: dict) -> None:
    """Начисляет очки за вердикт. Волчок: «почти» = не взят. Блиц: очко знатокам только за третий верный ответ подряд."""
    if g["mode"] != WHEEL:
        g["score"] += float(v["score"])
        return
    ok = v["level"] == "correct"
    cur = g["current"]
    if kind_of(g) in BLITZ_KINDS:
        if not ok:
            g["viewers"] += 1
        elif cur["sub"] >= cur["of"] - 1:
            g["experts"] += 1
        return
    g["experts" if ok else "viewers"] += 1


def blitz_continues(g: dict) -> bool:
    """Идёт блиц/суперблиц, текущий вопрос взят и впереди ещё вопросы — раунд продолжается."""
    cur = g.get("current") or {}
    v = g.get("verdict") or {}
    return (g["mode"] == WHEEL and kind_of(g) in BLITZ_KINDS and v.get("level") == "correct"
            and cur.get("sub", 0) < cur.get("of", 1) - 1)


def commit_round(g: dict) -> None:
    """Вердикт окончательный: начисляем очки и пишем в журнал. Вызывается один раз при переходе дальше."""
    v = g["verdict"]
    if g["phase"] != "review" or v is None or v.get("committed"):
        return
    _apply(g, v)
    v["committed"] = True
    cur = g["current"]
    g["log"].append({"qid": cur["qid"], "sector": cur["sector"], "kind": cur.get("kind", "normal"), "sub": cur.get("sub", 0),
                     "answer": g["answer"], "by": g["answered_by"],
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
    more_blitz = blitz_continues(g)
    commit_round(g)
    rec = g["log"][-1]
    if more_blitz:                       # следующий вопрос того же блица: сектор и стрелка не меняются
        cur = g["current"]
        cur["sub"] += 1
        cur["qid"] = g["blitz_q"][str(cur["sector"])][cur["sub"]]
        g["answer"] = g["answered_by"] = g["verdict"] = None
        g["phase"], g["round_started"], g["deadline"] = "think", now, now + BLITZ_THINK
        return rec
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
