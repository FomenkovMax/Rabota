"""Отчёт «из сохранённого»: пересобирает дайджест/PDF/дашборд/Excel за последние N часов из базы.
Ничего не собирает из Telegram и НЕ вызывает LLM — токены не тратятся, ответ за пару секунд."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..db import DB
from .digest import build_digest
from .export import export_files
from .pdf import make_onepager


def parse_hours(args: str | None, default: float | None = None, max_hours: float = 168.0) -> float | None:
    """'24 @Radar_Bank_Bot' -> 24.0; число — первое слово аргументов, остальное игнорируем; не больше недели."""
    first = (args or "").split()[:1]
    if first:
        w = first[0].replace(",", ".")
        if w.replace(".", "", 1).isdigit():
            return min(float(w), max_hours)
    return default


async def build_report(db: DB, hours: float, cfg: dict, out_dir: Path, tokens_left: int | None = None):
    """-> (текст дайджеста, [файлы], число событий за период)."""
    d = cfg["digest"]
    until = datetime.now(timezone.utc)
    since = until - timedelta(hours=hours)
    events = db.recent_events(hours / 24)
    n = int(hours) if float(hours).is_integer() else hours
    note = f"📋 <i>Отчёт за последние {n} ч из сохранённого (новые запросы к LLM не выполнялись)</i>"
    tokens = f"🪙 Токенов осталось: {tokens_left:,}".replace(",", " ") if tokens_left is not None else ""
    text = build_digest(events, since, until, 0, d["timezone"], d["max_events"], d["min_score"],
                        d.get("dashboard_min_score", 2), tokens, note)
    files: list[Path] = []
    dash = [e for e in events if e["relevance_score"] >= d.get("dashboard_min_score", 2)]
    if dash:
        files = export_files(dash, since, until, out_dir, d["timezone"])
        if (pdf := await make_onepager(events, since, until, out_dir, d["min_score"], d["timezone"])):
            files.insert(0, pdf)
    return text, files, len(events)
