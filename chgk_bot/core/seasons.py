"""Сезоны (календарный месяц), рейтинг, лиги (бронза/серебро/золото), награды и ачивки.
Все названия и пороги — в config/brand.json; здесь только правила подсчёта."""
import datetime as dt
import time

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .models import Attempt, Award, Game, User, UserAchievement
from .statsq import _streaks

TZ_H = 3   # границы месяца по Москве


def _tz(h: int = TZ_H) -> dt.timezone:
    return dt.timezone(dt.timedelta(hours=h))


def season_key(ts: float, tz_h: int = TZ_H) -> str:
    return dt.datetime.fromtimestamp(ts, _tz(tz_h)).strftime("%Y-%m")


def season_bounds(key: str, tz_h: int = TZ_H) -> tuple[float, float]:
    y, m = int(key[:4]), int(key[5:])
    start = dt.datetime(y, m, 1, tzinfo=_tz(tz_h))
    end = dt.datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=_tz(tz_h))
    return start.timestamp(), end.timestamp()


def league_of(points: float, brand: dict) -> dict:
    best = brand["leagues"][0]
    for lg in brand["leagues"]:
        if points >= lg["min_points"]:
            best = lg
    return best


def standings(factory, key: str, tz_h: int = TZ_H) -> list[dict]:
    a, b = season_bounds(key, tz_h)
    with factory() as s:
        rows = s.execute(
            select(Attempt.actor_id, func.count(), func.sum(Attempt.score)).where(
                Attempt.actor_id > 0, Attempt.mode == "solo", Attempt.ts >= a, Attempt.ts < b).group_by(Attempt.actor_id)).all()
        ok = dict(s.execute(select(Attempt.actor_id, func.count()).where(
            Attempt.actor_id > 0, Attempt.mode == "solo", Attempt.ts >= a, Attempt.ts < b, Attempt.score >= 1)
            .group_by(Attempt.actor_id)).all())
        users = {u.tg_id: u for u in s.scalars(select(User))}
    names = {k: u.name for k, u in users.items()}
    out = [{"user_id": uid, "name": names.get(uid, str(uid)), "photo": (users[uid].photo_url or "") if uid in users else "",
            "played": n, "points": float(pts or 0),
            "correct": ok.get(uid, 0), "accuracy": round(ok.get(uid, 0) / n, 3) if n else 0.0} for uid, n, pts in rows]
    out.sort(key=lambda r: (-r["points"], -r["accuracy"], r["user_id"]))
    for i, r in enumerate(out):
        r["rank"] = i + 1
    return out


def finalize_seasons(factory, brand: dict, now: float | None = None, tz_h: int = TZ_H) -> list[Award]:
    """Выдаёт награды за все закрытые месяцы, где они ещё не выданы. Идемпотентно."""
    now = now or time.time()
    cur = season_key(now, tz_h)
    with factory() as s:
        first = s.scalar(select(func.min(Attempt.ts)).where(Attempt.actor_id > 0, Attempt.mode == "solo"))
        done = {r for r in s.scalars(select(Award.season))}
    if first is None:
        return []
    keys, k = [], season_key(first, tz_h)
    while k < cur:
        keys.append(k)
        y, m = int(k[:4]), int(k[5:])
        k = f"{y + (m == 12)}-{m % 12 + 1:02d}"
    given = []
    for key in keys:
        if key in done:
            continue
        table = standings(factory, key, tz_h)
        if not table:
            continue
        w = table[0]
        kinds = ["owl"]
        if w["played"] >= 60 and w["accuracy"] >= 0.7:
            kinds.append("diamond_owl")
        with factory() as s:
            for kind in kinds:
                aw = Award(user_id=w["user_id"], season=key, kind=kind, points=w["points"], created_at=now)
                s.add(aw)
                given.append(aw)
            try:
                s.commit()
            except IntegrityError:
                s.rollback()
    return given


def check_achievements(factory, user_id: int, brand: dict) -> list[str]:
    """Проверяет условия ачивок и сохраняет новые. Возвращает коды только что полученных."""
    codes = set(brand.get("achievements", {}))
    with factory() as s:
        have = set(s.scalars(select(UserAchievement.code).where(UserAchievement.user_id == user_id)))
        if codes <= have:
            return []
        rows = s.execute(select(Attempt.score).where(Attempt.actor_id == user_id, Attempt.mode == "solo")
                         .order_by(Attempt.ts, Attempt.id)).scalars().all()
        won = 0
        if "captain_win" in codes and "captain_win" not in have:
            for g in s.scalars(select(Game).where(Game.status == "finished")):
                st = g.state
                if st.get("captain_id") == user_id and (st.get("experts", 0) > st.get("viewers", 0) if g.mode == "wheel"
                                                        else st.get("score", 0) > st.get("total", 1) / 2):
                    won += 1
        played = len(rows)
        ok = sum(1 for r in rows if r >= 1)
        best, _ = _streaks(list(rows))
        earned = {
            "first": played >= 1, "streak5": best >= 5, "streak10": best >= 10, "century": played >= 100,
            "sharp": played >= 30 and ok / played >= 0.8, "captain_win": won > 0,
        }
        new = [c for c in codes if earned.get(c) and c not in have]
        for c in new:
            s.add(UserAchievement(user_id=user_id, code=c, earned_at=time.time()))
        s.commit()
    return sorted(new)


def season_overview(factory, brand: dict, user_id: int, now: float | None = None, tz_h: int = TZ_H) -> dict:
    now = now or time.time()
    finalize_seasons(factory, brand, now, tz_h)
    key = season_key(now, tz_h)
    table = standings(factory, key, tz_h)
    me = next((r for r in table if r["user_id"] == user_id), None)
    pts = me["points"] if me else 0.0
    lg = league_of(pts, brand)
    nxt = next((x for x in brand["leagues"] if x["min_points"] > pts), None)
    _, end = season_bounds(key, tz_h)
    with factory() as s:
        awards = [{"user_id": a.user_id, "season": a.season, "kind": a.kind, "points": a.points}
                  for a in s.scalars(select(Award).order_by(Award.season.desc(), Award.id))]
        names = {u.tg_id: u.name for u in s.scalars(select(User))}
        mine = set(s.scalars(select(UserAchievement.code).where(UserAchievement.user_id == user_id)))
    for a in awards:
        a["name"] = names.get(a["user_id"], str(a["user_id"]))
    return {
        "season": key, "days_left": max(0, int((end - now) // 86400)), "standings": table[:20],
        "me": {"points": pts, "rank": me["rank"] if me else None, "league": lg,
               "next_league": nxt, "to_next": (nxt["min_points"] - pts) if nxt else 0},
        "awards": awards,
        "achievements": [{"code": c, **v, "earned": c in mine} for c, v in brand.get("achievements", {}).items()],
    }
