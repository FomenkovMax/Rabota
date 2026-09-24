"""Выгрузка свода в Excel, PDF и HTML."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SUPPORTED = ("xlsx", "pdf", "html")


def build_exports(config: Any, data: dict[str, Any],
                  formats: list[str]) -> list[Path]:
    """Готовит запрошенные форматы. Падение одного не ломает остальные."""
    from . import excel, pdf
    from ..report import write_report

    out_dir = config.path("export", "dir", default="data/export")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    base = f"Сравнение_{stamp}"

    html_path = out_dir / f"{base}.html"
    produced: list[Path] = []

    # HTML нужен и сам по себе, и как исходник для PDF.
    if "html" in formats or "pdf" in formats:
        write_report(html_path, data["html"])
        if "html" in formats:
            produced.append(html_path)

    if "xlsx" in formats:
        try:
            produced.append(excel.build(out_dir / f"{base}.xlsx", data))
        except Exception as exc:                   # noqa: BLE001
            log.error("Excel не собрался: %s", exc)

    if "pdf" in formats:
        try:
            produced.append(pdf.build(html_path, out_dir / f"{base}.pdf"))
        except Exception as exc:                   # noqa: BLE001
            log.error("PDF не собрался: %s", exc)

    return produced
