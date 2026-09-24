"""Общий браузерный адаптер: список разделов → продукты.

Сбер, ВТБ, ГенБанк и ЦМР различаются адресами разделов и тем, какую
проверку показывают до содержимого, но собираются одинаково: открыть
страницу настоящим браузером, дождаться отработки скриптов, прочитать
отрендеренный текст. Поэтому конкретный банк — это список разделов и
пара настроек, а не отдельный класс со своей логикой.
"""

from __future__ import annotations

import logging
from datetime import datetime

from .base import BankAdapter, CollectResult
from .browser import BrowserSettings, BrowserUnavailable, browser_session
from .generic_site import extract_products, to_products

log = logging.getLogger(__name__)


class SiteAdapter(BankAdapter):
    """Базовый класс для банков, которые читаются браузером."""

    #: (адрес раздела, категория продукта) — задаётся в наследнике.
    sections: tuple[tuple[str, str], ...] = ()
    #: Селектор, по которому понятно, что контент отрисовался.
    wait_for: str = ""
    #: Что известно про защиту — попадает в лог и в README.
    protection: str = ""
    #: Умеет ли адаптер выбирать регион на сайте. Пока не умеет — данные
    #: нельзя подписывать нужным регионом: сайт отдаст условия по своему
    #: усмотрению, обычно московские, и подпись «ЛНР» будет неправдой.
    sets_region: bool = False

    def collect(self) -> CollectResult:
        if not self.sections:
            return self._failed("не заданы разделы для обхода")

        settings = BrowserSettings.from_config(self.settings.get("browser"))
        now = datetime.now().isoformat(timespec="seconds")

        # Куки региона из настроек банка: [{name, value, domain}, ...].
        region_cookies = self.settings.get("region_cookies") or []
        applied = self.sets_region or bool(region_cookies)

        # Подписываем регионом только то, что действительно собрано по
        # этому региону. Иначе московские условия уехали бы в отчёт под
        # видом луганских, и никто бы этого не заметил.
        if applied:
            region_label = self.settings.get("region_label", "")
        else:
            region_label = "регион на сайте не выбран"
            log.warning(
                "%s: регион на сайте не задаётся, сайт отдаст условия по "
                "своему усмотрению (обычно московские). Данные помечены как "
                "собранные без выбора региона. Настроить: banks.%s.region_cookies",
                self.title, self.code,
            )

        products = []
        visited = 0
        failures: list[str] = []

        try:
            with browser_session(settings, cookies=region_cookies or None) as session:
                for url, category in self.sections:
                    try:
                        text = session.text(url, wait_for=self.wait_for)
                    except Exception as exc:        # noqa: BLE001
                        failures.append(f"{url}: {str(exc)[:80]}")
                        log.warning("%s: раздел %s не открылся — %s",
                                    self.title, url, str(exc)[:120])
                        continue

                    visited += 1
                    found = extract_products(text)
                    if not found:
                        log.warning("%s: в разделе %s условий не найдено. "
                                    "%s", self.title, url,
                                    "Возможно, изменилась вёрстка"
                                    if not self.protection
                                    else f"Защита: {self.protection}")
                        continue

                    products.extend(to_products(
                        found, bank=self.title, category=category,
                        region=region_label, collected_at=now, source_url=url,
                    ))
        except BrowserUnavailable as exc:
            return self._failed(str(exc))
        except Exception as exc:                    # noqa: BLE001
            return self._failed(f"сбор прерван: {exc}")

        if not products:
            detail = "; ".join(failures[:3]) if failures else "страницы открылись, но условий в них нет"
            return self._failed(
                f"не удалось извлечь ни одного продукта ({detail})"
            )

        if failures:
            log.warning("%s: разделов с ошибкой %s из %s",
                        self.title, len(failures), len(self.sections))

        result = self._result(products=products, promos=[],
                              pages_visited=visited, collected_at=now)
        object.__setattr__(result, "region_applied", applied)
        return result
