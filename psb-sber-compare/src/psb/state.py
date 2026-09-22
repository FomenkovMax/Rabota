"""Разбор SSR-состояния Angular (`<script id="serverApp-state">`).

Сайт ПСБ — Angular Universal. Весь контент страницы приезжает в одном
JSON-блобе рядом с разметкой, а ключи этого блоба — base64 от адресов
внутреннего API. Парсить этот JSON надёжнее, чем HTML-вёрстку: он не
поедет от редизайна.

Прямые запросы к `/back/api/v1/...` отдают 403 (WAF требует подписанные
заголовки), поэтому мы берём те же данные из готового ответа страницы.
"""

from __future__ import annotations

import base64
import binascii
import html as html_lib
import json
import logging
import re
from typing import Any, Iterator

log = logging.getLogger(__name__)

_STATE_RE = re.compile(
    r'<script id="serverApp-state" type="application/json">(.*?)</script>', re.S
)

# Angular экранирует спецсимволы внутри блоба своими краткими сущностями.
_UNESCAPE = {
    "&q;": '"',
    "&a;": "&",
    "&l;": "<",
    "&g;": ">",
    "&s;": "'",
    "&b;": "\\",
}


def extract_state(page_html: str) -> dict[str, Any]:
    """Достаёт и разбирает JSON-состояние страницы."""
    match = _STATE_RE.search(page_html)
    if not match:
        log.warning("На странице нет serverApp-state — вёрстка сайта могла измениться")
        return {}

    raw = match.group(1)
    for token, char in _UNESCAPE.items():
        raw = raw.replace(token, char)

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("serverApp-state не разобрался как JSON: %s", exc)
        return {}


def decode_key(key: str) -> str:
    """Ключи состояния — base64 от пути внутреннего API."""
    try:
        return base64.b64decode(key + "==").decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return key


def iter_entries(state: dict[str, Any]) -> Iterator[tuple[str, Any]]:
    """Обходит состояние, отдавая расшифрованный путь и значение."""
    for key, value in state.items():
        yield decode_key(key), value


def find_entries(state: dict[str, Any], marker: str) -> list[Any]:
    """Все значения, чей путь содержит `marker` (например 'getTariffTableRows')."""
    return [value for path, value in iter_entries(state) if marker in path]


# --- очистка текста -------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


def clean(value: Any) -> str:
    """HTML-фрагмент из CMS → читаемая строка.

    В контенте ПСБ повсюду `&nbsp;`, `&mdash;` и инлайновые теги подсказок —
    без очистки цифры не сравнить.
    """
    if value is None:
        return ""
    text = str(value)
    text = _TAG_RE.sub(" ", text)
    text = html_lib.unescape(text)
    text = text.replace("\xa0", " ").replace("—", "—").replace("–", "—")
    return _SPACE_RE.sub(" ", text).strip()
