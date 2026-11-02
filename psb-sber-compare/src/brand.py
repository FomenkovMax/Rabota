"""Фирменные цвета и логотипы банков для дашборда.

Замечание 03.11.2026: банки на дашборде не различить — все конкуренты одного
серого цвета, только подпись. Теперь у каждого банка свой цвет и логотип —
в таблицах, на графиках, в калькуляторе и каталоге.

Логотипы — config/brand/<код>.svg (квадратные, с карточек банков на
sravni.ru, 03.11.2026). Встраиваются в файл дашборда один раз — в CSS, — и
открываются в Telegram без интернета. Нового банка нет в списке — у него
нейтральный цвет и значок с первой буквой.
"""

from __future__ import annotations

import base64
import html
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "config" / "brand"

#: Банк → (код, цвет на светлой теме, цвет на тёмной теме).
BANKS: dict[str, tuple[str, str, str]] = {
    "Сбер": ("sber", "#21A038", "#2BC24A"),
    "ВТБ": ("vtb", "#0A2896", "#5C7CFA"),
    "ПСБ": ("psb", "#F26722", "#FF8A4C"),
    "Т-Банк": ("tbank", "#E6B800", "#FFDD2D"),
    "РостФинанс": ("rostfinance", "#14B8A6", "#2DD4BF"),
    "ЦМР": ("cmr", "#0EA5E9", "#38BDF8"),
}
_OTHER = ("other", "#8A8780", "#A8A59D")


def code(bank: str) -> str:
    return BANKS.get(bank, _OTHER)[0]


def color(bank: str) -> str:
    """Цвет банка как CSS-переменная — с учётом светлой и тёмной темы."""
    return f"var(--b-{code(bank)})"


def name(bank: str, *, bold: bool = False) -> str:
    """Логотип и название банка (HTML)."""
    text = html.escape(bank)
    if bold:
        text = f"<b>{text}</b>"
    letter = "" if code(bank) != "other" else html.escape((bank or "?")[:1])
    return f'<span class="bn"><i class="bl bl-{code(bank)}">{letter}</i>{text}</span>'


def _logo(c: str) -> str:
    path = FOLDER / f"{c}.svg"
    try:
        data = base64.b64encode(path.read_bytes()).decode()
    except OSError:
        return ""
    return f'.bl-{c}{{background-image:url("data:image/svg+xml;base64,{data}")}}'


def css() -> str:
    """Переменные цветов и логотипы — один раз на страницу."""
    light = "".join(f"--b-{c}:{l};" for c, l, _ in [*BANKS.values(), _OTHER])
    dark = "".join(f"--b-{c}:{d};" for c, _, d in [*BANKS.values(), _OTHER])
    logos = "".join(_logo(c) for c, _, _ in BANKS.values())
    return (f":root{{{light}}}"
            f'@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{{dark}}}}}'
            f':root[data-theme="dark"]{{{dark}}}'
            ".bn{display:inline-flex;align-items:center;gap:7px;white-space:nowrap}"
            ".bl{flex:none;display:inline-flex;align-items:center;justify-content:center;"
            "width:24px;height:24px;border-radius:7px;background:var(--b-other) center/cover no-repeat;"
            "font-style:normal;font-size:11px;font-weight:700;color:#fff;"
            "box-shadow:0 0 0 1px var(--border)}"
            ".bl-sber,.bl-vtb,.bl-psb,.bl-tbank,.bl-rostfinance,.bl-cmr{background-color:transparent}"
            + logos)


def js_codes() -> dict[str, str]:
    """Банк → код логотипа: для страниц, где строки рисует скрипт (калькулятор)."""
    return {bank: c for bank, (c, _, _) in BANKS.items()}
