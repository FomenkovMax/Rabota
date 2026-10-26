"""Запросы статистики по единой таблице attempts. actor_id — игрок (соло) или команда (отрицательный id чата)."""
import datetime as dt

from sqlalchemy import func, select

from .models import Attempt, Game, Question, User


def _streaks(scores: list[float]) -> tuple[int, int]:
    """(лучшая серия, текущая серия) подряд взятых вопросов; scores — по времени."""
    best = cur = 0
    for s in scores:
        cur = cur + 1 if s >= 1 else 0
        best = max(best, cur)
    return best, cur


def actor_stats(factory, actor_id: int, days: int = 14, now: float | None = None, tz_offset_h: int = 3) -> dict:
    """Сводка по игроку/команде: итоги, динамика по дням, разрез по пакетам, последние ответы."""
    now_dt = dt.datetime.fromtimestamp(now) if now else dt.datetime.now()
    with factory() as s:
        rows = s.execute(select(Attempt.ts, Attempt.score, Attempt.time_ms, Attempt.question_id)
                         .where(Attempt.actor_id == actor_id).order_by(Attempt.ts, Attempt.id)).all()
        qinfo = {}
        if rows:
            ids = {r[3] for r in rows}
            qinfo = {i: (txt, pack or topic) for i, txt, pack, topic in
                     s.execute(select(Question.id, Question.text, Question.pack, Question.topic).where(Question.id.in_(ids)))}
    played = len(rows)
    correct = sum(1 for r in rows if r[1] >= 1)
    close = sum(1 for r in rows if r[1] == 0.5)
    times = [r[2] for r in rows if r[2]]
    best, cur = _streaks([r[1] for r in rows])
    # динамика по дням (локальная дата сервера)
    daily = {}
    for i in range(days):
        d = (now_dt - dt.timedelta(days=days - 1 - i)).date()
        daily[d] = [0, 0]
    for ts, score, _t, _q in rows:
        d = dt.datetime.fromtimestamp(ts).date()
        if d in daily:
            daily[d][0] += 1
            daily[d][1] += 1 if score >= 1 else 0
    packs: dict[str, list[int]] = {}
    for _ts, score, _t, qid in rows:
        name = (qinfo.get(qid, ("", ""))[1] or "Без пакета")
        a = packs.setdefault(name, [0, 0])
        a[0] += 1
        a[1] += 1 if score >= 1 else 0
    top_packs = sorted(({"name": k, "played": v[0], "correct": v[1]} for k, v in packs.items()),
                       key=lambda x: -x["played"])[:5]
    recent = [{"text": (qinfo.get(q, ("", ""))[0] or "")[:90], "score": sc, "ts": ts} for ts, sc, _t, q in rows[-8:]][::-1]
    return {
        "played": played, "correct": correct, "close": close,
        "points": sum(r[1] for r in rows), "accuracy": round(correct / played, 3) if played else 0.0,
        "avg_time_ms": int(sum(times) / len(times)) if times else None,
        "best_streak": best, "streak": cur,
        "daily": [{"date": d.isoformat(), "played": v[0], "correct": v[1]} for d, v in daily.items()],
        "packs": top_packs, "recent": recent,
    }


def team_extra(factory, team_id: int, limit: int = 10) -> dict:
    """История игр команды и вклад игроков (кто сдавал ответы капитаном; соло-точность участников)."""
    with factory() as s:
        games = s.scalars(select(Game).where(Game.team_id == team_id, Game.status == "finished")
                          .order_by(Game.updated_at.desc()).limit(limit)).all()
        users = {u.tg_id: u for u in s.scalars(select(User))}
        names = {k: u.name for k, u in users.items()}
        photos = {k: u.photo_url or "" for k, u in users.items()}
        solo = s.execute(select(Attempt.actor_id, func.count()).where(Attempt.actor_id > 0)
                         .group_by(Attempt.actor_id)).all()
        solo_ok = dict(s.execute(select(Attempt.actor_id, func.count()).where(Attempt.actor_id > 0, Attempt.score >= 1)
                                 .group_by(Attempt.actor_id)).all())
    hist, answered = [], {}
    for g in games:
        st = g.state
        hist.append({"date": dt.datetime.fromtimestamp(g.updated_at).strftime("%d.%m"), "mode": g.mode,
                     "score": st.get("score"), "total": st.get("total"), "experts": st.get("experts"), "viewers": st.get("viewers")})
        for r in st.get("log", []):
            if r.get("by"):
                a = answered.setdefault(r["by"], [0, 0])
                a[0] += 1
                a[1] += 1 if r["level"] == "correct" else 0
    players = [{"id": uid, "name": names.get(uid, str(uid)), "photo": photos.get(uid, ""), "solo_played": n, "solo_correct": solo_ok.get(uid, 0),
                "as_captain": answered.get(uid, [0, 0])[0], "captain_correct": answered.get(uid, [0, 0])[1]}
               for uid, n in solo]
    players.sort(key=lambda p: -(p["solo_played"] + p["as_captain"]))
    return {"games": hist[::-1], "players": players}
