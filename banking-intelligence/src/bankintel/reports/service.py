"""Генерация всех форматов отчёта из одного набора данных."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from bankintel.reports.dataset import build_dataset
from bankintel.reports.render_html import render_html, render_pdf
from bankintel.reports.render_pptx import render_pptx
from bankintel.reports.render_xlsx import render_xlsx

FORMATS = ("pdf", "html", "pptx", "xlsx")


@dataclass
class ReportBundle:
    dataset_id: str
    dataset: dict
    paths: dict[str, Path]


def _render_all(ds: dict) -> dict[str, bytes | str]:
    return {"html": render_html(ds), "pdf": render_pdf(ds), "pptx": render_pptx(ds), "xlsx": render_xlsx(ds)}


async def generate_reports(session: AsyncSession, out_dir: Path, now: datetime | None = None) -> ReportBundle:
    """Строит набор данных (с проверкой) один раз и рендерит из него все форматы.
    Бросает DatasetError, если данные нельзя проследить до источников."""
    now = now or datetime.now(UTC)
    ds = await build_dataset(session, now)
    rendered = await asyncio.to_thread(_render_all, ds)  # WeasyPrint и Plotly синхронные
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"bankintel_{now:%Y%m%d}_{ds['meta']['dataset_id']}"
    paths = {}
    for fmt in FORMATS:
        data = rendered[fmt]
        path = out_dir / f"{stem}.{fmt}"
        path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
        paths[fmt] = path
    return ReportBundle(ds["meta"]["dataset_id"], ds, paths)
