"""Ключевая ставка Банка России на дату среза.

Нужна как ориентир для проверки правдоподобия: вклад сильно выше ключевой
или кредит дешевле неё почти всегда означает промо, чужую программу или
ошибку разбора. Берём с cbr.ru, со страницы истории ключевой ставки.

Если сайт ЦБ недоступен, берётся значение из настроек (key_rate), а если
нет и его — ставка неизвестна, и проверки, которым она нужна, честно
пропускаются. Подставлять «примерную» ставку нельзя.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import requests

log = logging.getLogger(__name__)

URL = "https://www.cbr.ru/hd_base/KeyRate/"

# В таблице на странице строки идут парами ячеек: дата, ставка.
_ROW = re.compile(r"<td>\s*(\d{2}\.\d{2}\.\d{4})\s*</td>\s*<td>\s*(\d{1,2},\d{2})\s*</td>")


@dataclass
class KeyRate:
    value: float          # % годовых
    on: str               # дата, на которую действует, ГГГГ-ММ-ДД
    source: str           # откуда взята: cbr.ru или settings.yaml

    @property
    def label(self) -> str:
        day = datetime.strptime(self.on, "%Y-%m-%d").strftime("%d.%m.%Y")
        return f"{self.value:.2f}".replace(".", ",") + f" % на {day}"


def parse(html: str, *, on_or_before: date | None = None) -> KeyRate | None:
    """Самая свежая ставка из таблицы на странице ЦБ (не позже даты, если задана)."""
    rows = []
    for day, value in _ROW.findall(html):
        try:
            on = datetime.strptime(day, "%d.%m.%Y").date()
        except ValueError:
            continue
        if on_or_before is None or on <= on_or_before:
            rows.append((on, float(value.replace(",", "."))))
    if not rows:
        return None
    on, value = max(rows)
    return KeyRate(value=value, on=on.isoformat(), source="cbr.ru")


def from_settings(settings: dict[str, Any] | None) -> KeyRate | None:
    """Ставка из settings.yaml: key_rate: {value: 14.0, date: 2026-10-06}."""
    data = settings or {}
    try:
        value = float(data["value"])
    except (KeyError, TypeError, ValueError):
        return None
    on = str(data.get("date") or date.today().isoformat())
    return KeyRate(value=value, on=on, source="settings.yaml")


def fetch(settings: dict[str, Any] | None = None, *, timeout: float = 20) -> KeyRate | None:
    """Ставка с cbr.ru; при неудаче — из настроек; иначе None."""
    try:
        response = requests.get(URL, timeout=timeout,
                                headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        rate = parse(response.text)
        if rate:
            log.info("Ключевая ставка ЦБ: %s", rate.label)
            return rate
        log.warning("На странице ЦБ не нашлась таблица ключевой ставки")
    except requests.RequestException as exc:
        log.warning("Сайт ЦБ недоступен: %s", exc)

    rate = from_settings(settings)
    if rate:
        log.info("Ключевая ставка из настроек: %s", rate.label)
    else:
        log.warning("Ключевая ставка неизвестна — проверки по ней пропущены")
    return rate


def on_date(day: str | date, *, timeout: float = 20) -> KeyRate | None:
    """Ставка, действовавшая на дату, — для старых сборов, где её не записали.

    Ставка не публикуется в выходные, поэтому берём месяц до даты и
    последнее значение не позже неё.
    """
    target = day if isinstance(day, date) else date.fromisoformat(str(day)[:10])
    start = target - timedelta(days=31)
    params = {"UniDbQuery.Posted": "True",
              "UniDbQuery.From": start.strftime("%d.%m.%Y"),
              "UniDbQuery.To": target.strftime("%d.%m.%Y")}
    try:
        response = requests.get(URL, params=params, timeout=timeout,
                                headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
    except requests.RequestException as exc:
        log.warning("Ключевая ставка на %s: сайт ЦБ недоступен — %s", target, exc)
        return None
    return parse(response.text, on_or_before=target)


def ensure(storage: object, run_id: int, started_at: str,
           settings: dict[str, Any] | None = None) -> KeyRate | None:
    """Ставка сбора: из базы, а если её там нет — с cbr.ru на дату сбора.

    Найденную записываем в базу, чтобы не ходить на сайт ЦБ каждый раз.
    Ставка из настроек — последний вариант и только для сбора того же дня,
    на который она указана: подставлять сегодняшнюю ставку в прошлогодний
    срез нельзя.
    """
    value, on = storage.key_rate_of(run_id)            # type: ignore[attr-defined]
    if value is not None:
        return KeyRate(value=value, on=on or started_at[:10], source="база")
    rate = on_date(started_at[:10])
    if rate is None:
        manual = from_settings(settings)
        if manual and manual.on == started_at[:10]:
            rate = manual
    if rate is not None:
        storage.set_key_rate(run_id, rate)             # type: ignore[attr-defined]
    return rate
