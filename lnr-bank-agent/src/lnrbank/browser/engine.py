"""Браузер: один Chromium на запуск, контекст на банк, паузы, robots.txt, распознавание блокировок.

Проверка сертификатов не отключается, stealth-плагинов и подмены отпечатков нет (D-7).
"""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright
from playwright.sync_api import Error as PWError

from lnrbank.browser.antibot import detect_block
from lnrbank.browser.robots import RobotsGate
from lnrbank.config import Settings


@dataclass
class Visit:
    ok: bool
    url: str
    status: int | None = None
    reason: str = ""


class BrowserEngine:
    def __init__(self, settings: Settings, verify, sleep=time.sleep) -> None:
        self.settings = settings
        self.sleep = sleep
        self.robots = RobotsGate(
            fetch=lambda url: httpx.get(url, verify=verify, timeout=15).raise_for_status().text
        )
        self._pw = None
        self.browser: Browser | None = None
        self._contexts: dict[str, BrowserContext] = {}
        self._first_visit = True

    def __enter__(self) -> BrowserEngine:
        cfg = self.settings.browser
        exe = os.environ.get("LNRBANK_CHROMIUM") or cfg.executable_path
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(
            headless=cfg.headless, executable_path=str(exe) if exe else None
        )
        return self

    def __exit__(self, *exc) -> None:
        for ctx in self._contexts.values():
            ctx.close()
        if self.browser:
            self.browser.close()
        if self._pw:
            self._pw.stop()

    def page(self, bank: str) -> Page:
        if bank not in self._contexts:
            cfg = self.settings.browser
            self._contexts[bank] = self.browser.new_context(
                locale=cfg.locale, timezone_id=cfg.timezone, viewport={"width": 1366, "height": 900}
            )
        return self._contexts[bank].new_page()

    def _pause(self) -> None:
        if not self._first_visit:
            self.sleep(random.uniform(*self.settings.browser.delay_s))  # noqa: S311 — не криптография
        self._first_visit = False

    def visit(self, page: Page, url: str) -> Visit:
        if not self.robots.allowed(url):
            return Visit(False, url, reason="blocked_by_robots")
        self._pause()
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(2000)
        except PWError as exc:
            return Visit(False, url, reason=f"ошибка загрузки: {str(exc).splitlines()[0]}"[:300])
        status = resp.status if resp else None
        blocked = detect_block(page.content(), page.inner_text("body"))
        if blocked:
            return Visit(False, url, status, reason=f"blocked: {blocked}")
        if status and status >= 400:
            return Visit(False, url, status, reason=f"HTTP {status}")
        return Visit(True, url, status)

    @staticmethod
    def screenshot(page: Page, path: Path) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(path))
        return str(path)
