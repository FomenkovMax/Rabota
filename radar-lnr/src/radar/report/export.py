"""Формирует файлы-приложения к дайджесту: HTML-дашборд + Excel."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..config import load_channels
from .dashboard import render_dashboard
from .excel import events_workbook


def export_files(events: list[dict], since: datetime, until: datetime, out_dir: Path,
                 tz: str = "Europe/Moscow") -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    districts = {c["username"]: c["district"] for c in load_channels() if c.get("district")}
    stamp = until.astimezone(ZoneInfo(tz)).strftime("%Y%m%d_%H%M")
    html = out_dir / f"radar_lnr_{stamp}.html"
    xlsx = out_dir / f"radar_lnr_{stamp}.xlsx"
    html.write_text(render_dashboard(events, since, until, districts, tz), encoding="utf-8")
    xlsx.write_bytes(events_workbook(events, districts))
    return [html, xlsx]
