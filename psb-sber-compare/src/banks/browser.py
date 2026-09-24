"""Работа через настоящий браузер — для сайтов с JS-проверкой.

Сбер отдаёт челлендж F5 (переменная `bobcmn` в теле), ГенБанк — Qrator
(`qauth.js` и кука `qrator_jsr`), ВТБ подгружает условия отдельными
запросами уже после загрузки страницы. Во всех трёх случаях ответ на
обычный HTTP-запрос содержит не данные, а проверку.

Здесь нет обхода защиты: Playwright запускает настоящий Chromium, который
выполняет ту же проверку, что и браузер обычного посетителя, и открывает
ту же публичную страницу. Мы не подделываем подписи и не трогаем закрытые
API — просто читаем страницу так, как её видит человек.

Темп обхода при этом остаётся вежливым: пауза между страницами и
ограничение на число одновременных вкладок.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

log = logging.getLogger(__name__)

CHROMIUM_CANDIDATES = (
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    "/opt/pw-browsers/chromium/chrome-linux/chrome",
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)



def _normalise_cookies(cookies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Приводит куки из настроек к виду, который принимает Playwright.

    В YAML значение куки пишется как есть: 94 разбирается в число, true —
    в булево. Playwright ждёт строки и отвергает остальное. Отдельно
    важен регистр: у булева Python строковый вид «True», а сайты ждут
    «true». Ещё Playwright требует пару domain + path, а path в
    настройках банка обычно не указывают — подставляем корень.
    """
    ready = []
    for cookie in cookies:
        item = dict(cookie)
        value = item.get("value")
        if isinstance(value, bool):
            item["value"] = "true" if value else "false"
        elif not isinstance(value, str):
            item["value"] = str(value)
        if "url" not in item:
            item.setdefault("path", "/")
        ready.append(item)
    return ready


class BrowserUnavailable(RuntimeError):
    """Playwright не установлен или браузер не найден."""


def find_chromium() -> str | None:
    """Путь к браузеру, если он лежит не там, где Playwright ищет сам."""
    explicit = os.environ.get("PSB_CHROMIUM_PATH")
    if explicit and Path(explicit).exists():
        return explicit
    for candidate in CHROMIUM_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


@dataclass
class BrowserSettings:
    """Настройки браузерного сбора."""

    headless: bool = True
    timeout_ms: int = 45_000
    #: Сколько ждать после загрузки, чтобы отработали JS-проверка и XHR.
    settle_ms: int = 5_000
    #: Пауза между страницами — вежливость к чужому серверу.
    pause_s: float = 2.0
    #: Прокси вида http://host:port, если он нужен.
    proxy: str = ""
    #: Игнорировать ошибки сертификата. По умолчанию выключено.
    #: Включать только если российский корень не установлен в систему —
    #: и понимать, что это ослабляет проверку подлинности сайта.
    ignore_https_errors: bool = False

    @classmethod
    def from_config(cls, data: dict[str, Any] | None) -> "BrowserSettings":
        data = data or {}
        return cls(
            headless=bool(data.get("headless", True)),
            timeout_ms=int(data.get("timeout_ms", 45_000)),
            settle_ms=int(data.get("settle_ms", 5_000)),
            pause_s=float(data.get("pause_s", 2.0)),
            proxy=str(data.get("proxy", "") or ""),
            ignore_https_errors=bool(data.get("ignore_https_errors", False)),
        )


class BrowserSession:
    """Одна браузерная сессия на весь обход банка."""

    def __init__(self, settings: BrowserSettings, *, cookies: list[dict] | None = None) -> None:
        self.settings = settings
        self.cookies = cookies or []
        self._playwright = None
        self._browser = None
        self._context = None

    def start(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserUnavailable(
                "Не установлен Playwright. Выполни:\n"
                "  pip install playwright\n"
                "  playwright install chromium"
            ) from exc

        self._playwright = sync_playwright().start()
        launch: dict[str, Any] = {
            "headless": self.settings.headless,
            # Флаг убирает navigator.webdriver — не для маскировки, а потому
            # что часть сайтов на нём ломает вёрстку и отдаёт пустую страницу.
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        path = find_chromium()
        if path:
            launch["executable_path"] = path
        if self.settings.proxy:
            launch["proxy"] = {"server": self.settings.proxy}

        try:
            self._browser = self._playwright.chromium.launch(**launch)
        except Exception as exc:
            self.close()
            raise BrowserUnavailable(
                f"Не удалось запустить Chromium: {exc}\n"
                "Проверь: playwright install chromium"
            ) from exc

        self._context = self._browser.new_context(
            locale="ru-RU",
            user_agent=USER_AGENT,
            viewport={"width": 1440, "height": 900},
            ignore_https_errors=self.settings.ignore_https_errors,
        )
        self._context.set_default_timeout(self.settings.timeout_ms)
        if self.cookies:
            self._context.add_cookies(_normalise_cookies(self.cookies))

    def fetch(self, url: str, *, wait_for: str = "") -> str:
        """Открывает страницу и возвращает её HTML после отработки скриптов."""
        if self._context is None:
            raise BrowserUnavailable("Сессия браузера не запущена")

        page = self._context.new_page()
        try:
            response = page.goto(url, wait_until="domcontentloaded")
            status = response.status if response else 0

            if wait_for:
                try:
                    page.wait_for_selector(wait_for, timeout=self.settings.timeout_ms)
                except Exception:
                    log.debug("Не дождались селектора %s на %s", wait_for, url)

            # Время на JS-проверку и на дозагрузку условий отдельными запросами.
            page.wait_for_timeout(self.settings.settle_ms)

            html = page.content()
            if status >= 400:
                log.warning("%s → HTTP %s", url, status)
            return html
        finally:
            page.close()
            time.sleep(self.settings.pause_s)

    def text(self, url: str, *, wait_for: str = "") -> str:
        """Видимый текст страницы — когда разметка не нужна."""
        if self._context is None:
            raise BrowserUnavailable("Сессия браузера не запущена")
        page = self._context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded")
            if wait_for:
                try:
                    page.wait_for_selector(wait_for, timeout=self.settings.timeout_ms)
                except Exception:
                    pass
            page.wait_for_timeout(self.settings.settle_ms)
            return page.inner_text("body")
        finally:
            page.close()
            time.sleep(self.settings.pause_s)

    def snapshot(self, url: str, *, wait_for: str = "") -> tuple[str, str]:
        """Разметка и видимый текст одной страницы за одну загрузку.

        Порознь fetch и text открывают её дважды, а это лишний поход на
        чужой сервер и двойное ожидание скриптов.
        """
        if self._context is None:
            raise BrowserUnavailable("Сессия браузера не запущена")

        page = self._context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded")
            if wait_for:
                try:
                    page.wait_for_selector(wait_for, timeout=self.settings.timeout_ms)
                except Exception:
                    log.debug("Не дождались селектора %s на %s", wait_for, url)
            page.wait_for_timeout(self.settings.settle_ms)
            return page.content(), page.inner_text("body")
        finally:
            page.close()
            time.sleep(self.settings.pause_s)

    def close(self) -> None:
        for item in (self._context, self._browser, self._playwright):
            if item is None:
                continue
            try:
                item.stop() if hasattr(item, "stop") else item.close()
            except Exception:
                pass
        self._context = self._browser = self._playwright = None


@contextmanager
def browser_session(settings: BrowserSettings,
                    cookies: list[dict] | None = None) -> Iterator[BrowserSession]:
    session = BrowserSession(settings, cookies=cookies)
    session.start()
    try:
        yield session
    finally:
        session.close()
