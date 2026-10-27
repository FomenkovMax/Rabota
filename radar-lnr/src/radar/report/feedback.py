"""Оценки полезности новостей (кнопки 1–5): клавиатура, статистика и калибровка звёзд для LLM."""
from __future__ import annotations

from collections import defaultdict
from html import escape

from ..llm.schemas import CATEGORIES

PREFIX = "v"          # callback_data: v:<event_id>:<оценка>


def vote_data(event_id: int, score: int) -> str:
    return f"{PREFIX}:{event_id}:{score}"


def parse_vote(data: str | None) -> tuple[int, int] | None:
    try:
        p, eid, sc = (data or "").split(":")
        if p == PREFIX and 1 <= int(sc) <= 5:
            return int(eid), int(sc)
    except ValueError:
        pass
    return None


def vote_rows(event_id: int, mine: int | None = None, avg: float | None = None, n: int = 0) -> list[list[tuple[str, str]]]:
    """Кнопки (текст, callback_data). Выбранная оценка помечена; под кнопками — итог голосования."""
    row = [(f"[{i}]" if i == mine else str(i), vote_data(event_id, i)) for i in range(1, 6)]
    return [row]


def vote_caption(avg: float | None, n: int, mine: int | None) -> str:
    if not n:
        return "Насколько полезна новость? 1 — мимо, 5 — очень"
    me = f"твоя {mine}, " if mine else ""
    return f"Полезность: {me}средняя {avg:.1f} ({n} гол.)"


def feedback_report(rows: list[dict], min_votes: int = 1) -> str:
    """Сводка: средняя оценка коллег против звёзд модели, по категориям. Для /feedback (админ)."""
    rows = [r for r in rows if r["n"] >= min_votes]
    if not rows:
        return "Оценок пока нет. Они появятся, когда коллеги начнут жать кнопки под новостями."
    by_star: dict[int, list[float]] = defaultdict(list)
    by_cat: dict[int, list[float]] = defaultdict(list)
    for r in rows:
        by_star[r["llm"]].append(r["avg"])
        by_cat[r["category"]].append(r["avg"] - r["llm"])
    out = [f"📊 <b>Полезность новостей</b> (оценено событий: {len(rows)}, голосов: {sum(r['n'] for r in rows)})",
           "", "<b>Звёзды модели → средняя оценка коллег</b>"]
    for star in sorted(by_star):
        v = by_star[star]
        out.append(f"⭐{star}: {sum(v) / len(v):.1f} (событий {len(v)})")
    out += ["", "<b>Перекос по категориям</b> (оценка коллег минус звёзды модели)"]
    for cat, diffs in sorted(by_cat.items()):
        d = sum(diffs) / len(diffs)
        mark = "модель занижает" if d > 0.7 else "модель завышает" if d < -0.7 else "ок"
        out.append(f"{CATEGORIES[cat][0]} {escape(CATEGORIES[cat][1])}: {d:+.1f} — {mark} ({len(diffs)})")
    if min(len(v) for v in by_star.values()) < 5:
        out += ["", "ℹ️ Данных пока мало — выводы осторожно, нужно хотя бы 5 оценённых событий на каждую звезду."]
    return "\n".join(out)


def calibration_text(rows: list[dict], min_votes: int = 2, limit: int = 4) -> str:
    """Примеры для промпта анализа: что коллеги признали полезным / бесполезным. Пусто, пока данных мало."""
    rows = [r for r in rows if r["n"] >= min_votes]
    if len(rows) < 6:
        return ""
    good = sorted((r for r in rows if r["avg"] >= 4), key=lambda r: -r["avg"])[:limit]
    bad = sorted((r for r in rows if r["avg"] <= 2), key=lambda r: r["avg"])[:limit]
    if not good and not bad:
        return ""
    lines = ["\n\nКАЛИБРОВКА ПО ОЦЕНКАМ СОТРУДНИКОВ БАНКА (реальная полезность новостей, 1–5). Учитывай при выставлении relevance_score:"]
    for r in good:
        lines.append(f"- ПОЛЕЗНО ({r['avg']:.1f}): {r['title']}")
    for r in bad:
        lines.append(f"- БЕСПОЛЕЗНО ({r['avg']:.1f}): {r['title']}")
    return "\n".join(lines)
