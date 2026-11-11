"""Распознавание антибот-страниц и капчи. Обходить их агент не пытается (D-7)."""

from __future__ import annotations

HTML_MARKERS = {
    "TSPD": "JS-проверка браузера (TSPD)",
    "bobcmn": "JS-проверка браузера (TSPD)",
    "smartcaptcha": "капча",
    "g-recaptcha": "капча",
    "hcaptcha": "капча",
    "cf-challenge": "проверка браузера",
}
TEXT_MARKERS = {
    "не робот": "капча",
    "проверка браузера": "проверка браузера",
    "подтвердите, что вы": "капча",
    "access denied": "доступ запрещён",
    "доступ ограничен": "доступ запрещён",
}


def detect_block(html: str, text: str) -> str | None:
    """Причина блокировки или None, если это обычная страница."""
    for marker, reason in HTML_MARKERS.items():
        if marker in html:
            return reason
    lowered = text.casefold()
    for marker, reason in TEXT_MARKERS.items():
        if marker in lowered:
            return reason
    return None
