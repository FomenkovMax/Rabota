"""Свод в PDF.

PDF печатаем из того же HTML-дашборда через Chromium, который уже стоит
ради браузерного сбора. Это не экономия ради экономии: отчёт в PDF и на
экране показывают одни и те же цифры, свёрстанные одним кодом, и
разойтись они не могут. Отдельный генератор PDF означал бы вторую вёрстку
и вторую возможность соврать.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..banks.browser import BrowserSettings, BrowserUnavailable, find_chromium

log = logging.getLogger(__name__)


class PdfUnavailable(RuntimeError):
    """PDF собрать нечем."""


def build(html_path: str | Path, pdf_path: str | Path,
          settings: BrowserSettings | None = None) -> Path:
    """Печатает готовый HTML-отчёт в PDF."""
    html_path = Path(html_path)
    pdf_path = Path(pdf_path)
    if not html_path.exists():
        raise PdfUnavailable(f"Нет исходного отчёта: {html_path}")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    settings = settings or BrowserSettings()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise PdfUnavailable(
            "Для PDF нужен Playwright: pip install playwright && "
            "playwright install chromium"
        ) from exc

    launch = {"headless": True}
    path = find_chromium()
    if path:
        launch["executable_path"] = path

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(**launch)
            page = browser.new_page()
            # Печатаем светлую тему: тёмный фон съедает тонер и плохо
            # читается на проекторе.
            page.emulate_media(media="print", color_scheme="light")
            page.goto(html_path.resolve().as_uri(), wait_until="load")
            page.wait_for_timeout(1200)
            # Раскрываем свёрнутые блоки — в PDF кликнуть уже нельзя.
            page.evaluate(
                "document.querySelectorAll('details').forEach(d => d.open = true)"
            )
            page.wait_for_timeout(400)
            page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                margin={"top": "12mm", "bottom": "12mm",
                        "left": "10mm", "right": "10mm"},
            )
            browser.close()
    except BrowserUnavailable:
        raise
    except Exception as exc:                       # noqa: BLE001
        raise PdfUnavailable(f"Не удалось напечатать PDF: {exc}") from exc

    log.info("PDF собран: %s", pdf_path)
    return pdf_path
