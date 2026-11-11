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


# --- 3D-иконки разделов ------------------------------------------------------
# Сгенерированы в Higgsfield 03.11.2026 в одном стиле («глянцевый 3D, как в
# СберБанк Онлайн»), сжаты в WebP 128×128 (~7 КБ): config/brand/icons/*.webp.

#: Слово в заголовке раздела или категории → иконка. Первое совпадение.
SECTION_ICONS = (
    ("Накопительн", "savings"), ("Вклад", "deposits"), ("Сбережени", "deposits"),
    ("Ипотек", "mortgage"), ("Кредитные карты", "cards"), ("Дебетовые карты", "cards"),
    ("Банковские карты", "cards"), ("Карты", "cards"), ("Кредит", "loans"),
    ("ЛНР", "region"), ("Присутствие", "region"), ("Охват", "region"),
    ("Калькулятор", "calc"),
    ("Главное", "market"), ("Место Сбера", "market"), ("на фоне рынка", "market"),
    ("Карта ставок", "market"), ("Позиционирование", "market"), ("Светофор", "market"),
    ("Дельта", "market"), ("История", "market"), ("Воронка", "market"),
    ("Качество", "market"), ("Каталог", "cards"), ("Акции", "deposits"),
    ("Специальные", "deposits"), ("Изменения", "market"),
)


def icons_css() -> str:
    out = [".sic{flex:none;display:inline-block;width:34px;height:34px;margin:-6px 8px -8px -2px;"
           "background:center/contain no-repeat;vertical-align:middle}"
           "h2:has(.sic){border-left:0;padding-left:0;display:flex;align-items:center}"
           "summary .sic{width:26px;height:26px;margin:-4px 6px -6px 0}"]
    for name in {n for _, n in SECTION_ICONS}:
        try:
            data = base64.b64encode((FOLDER / "icons" / f"{name}.webp").read_bytes()).decode()
        except OSError:
            continue
        out.append(f'.ic-{name}{{background-image:url("data:image/webp;base64,{data}")}}')
    return "".join(out)


def _icon_for(title: str) -> str:
    return next((name for word, name in SECTION_ICONS if word in title), "")


def decorate(page: str) -> str:
    """Иконки в заголовки разделов (h2) и категорий (summary) готовой страницы."""
    import re

    def h2(match: "re.Match[str]") -> str:
        name = _icon_for(match.group(2))
        if not name or "sic" in match.group(2):
            return match.group(0)
        return f'{match.group(1)}<i class="sic ic-{name}"></i>{match.group(2)}'

    page = re.sub(r"(<h2[^>]*>)([^<]+)", h2, page)
    return re.sub(r'(<details class="cat"[^>]*><summary>)([^<]+)', h2, page)
