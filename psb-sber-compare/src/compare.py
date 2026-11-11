"""Сопоставление продуктов и расчёт светофора.

Пары подбираются автоматически по сути продукта, а не по названию и не по
цифрам: см. availability.matrix (программа, сегмент клиента, механизм и тип
ставки). Ручного списка пар нет (решение 03.11.2026). В светофор идут только
прямые аналоги: ошибка в паре — неверная цифра в отчёте у руководителя,
поэтому «похожий» продукт лучше оставить без сравнения, чем сравнить зря.

Светофор (с позиции Сбера, дельта = ставка Сбера − ставка ПСБ):
    🟢 зелёный  — Сбер выгоднее клиенту (ставка ниже) более чем на порог
    🟡 жёлтый   — паритет в пределах порога
    🔴 красный  — проигрываем ПСБ больше верхнего порога
    ⚪ серый    — данных не хватает, сравнение невозможно
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable

from . import conditions

log = logging.getLogger(__name__)

GREEN, YELLOW, RED, GREY = "green", "yellow", "red", "grey"


def pp(value: float) -> str:
    """Процентные пункты по-русски: десятичная запятая, а не точка."""
    return f"{value:.2f}".replace(".", ",") + " п.п."

LIGHT_LABEL = {
    GREEN: "Выигрываем",
    YELLOW: "Паритет",
    RED: "Проигрываем",
    GREY: "Нет данных",
}

# Для вкладов и накопительных счетов выгода клиента — ставка ВЫШЕ.
# Для кредитов — НИЖЕ. Без этого различия светофор врёт на половине каталога.
HIGHER_IS_BETTER = {"Вклады", "Накопительные счета", "Долгосрочные сбережения",
                    "Инвестиционные услуги"}


@dataclass
class Thresholds:
    """Пороги светофора в процентных пунктах."""

    parity: float = 0.5   # дельта меньше — паритет (жёлтый)
    loss: float = 1.0     # дельта хуже этой — красный

    @classmethod
    def from_config(cls, data: dict[str, Any] | None) -> "Thresholds":
        data = data or {}
        return cls(
            parity=float(data.get("parity_pp", 0.5)),
            loss=float(data.get("loss_pp", 1.0)),
        )


@dataclass
class Comparison:
    """Одна строка отчёта: пара продуктов и вердикт.

    Поле `psb` исторически названо по первому банку в сравнении; сейчас
    в нём лежит продукт любого банка-конкурента, а `sber` — наш.
    """

    pair_id: str
    label: str                    # как называем пару в отчёте
    category: str
    psb: Any | None = None       # продукт банка-конкурента
    sber: Any | None = None

    # Ставки, которые реально сравнивались (граница зависит от категории).
    psb_rate: float | None = None
    sber_rate: float | None = None
    rate_bound: str = "min"              # min — «ставка от», max — «ставка до»

    delta_rate: float | None = None      # ставка Сбера − ставка ПСБ
    delta_apr: float | None = None
    light: str = GREY
    reason: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def light_label(self) -> str:
        return LIGHT_LABEL[self.light]


# --- нормализация названий ------------------------------------------------

_NOISE_RE = re.compile(
    r"\b(банк|псб|сбер|сбербанк|пао|в\s+псб|от\s+псб|для\s+физических\s+лиц|"
    r"физлиц|онлайн|новый|новая)\b", re.I
)
_PUNCT_RE = re.compile(r"[^\w\s]", re.U)
_SPACE_RE = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    text = unicodedata.normalize("NFKC", title or "").lower().replace("ё", "е")
    text = _PUNCT_RE.sub(" ", text)
    text = _NOISE_RE.sub(" ", text)
    return _SPACE_RE.sub(" ", text).strip()



# --- сопоставление --------------------------------------------------------

def from_matrix(rows: Iterable[Any], thresholds: Thresholds) -> list[Comparison]:
    """Строки светофора из матрицы аналогов (availability.matrix).

    Пары подбираются автоматически по сути продукта: та же категория и
    программа, тот же сегмент клиента (пенсионер, ребёнок, зарплатный…),
    тот же механизм ставки (плавающая от ключевой, валюта вклада) и тот же
    тип ставки (базовая, на новые деньги…). В светофор идут только прямые
    аналоги — «похожие» продукты (Cell.close = False) остаются в своде по
    ЛНР с пометкой «не прямой аналог», но ставки по ним не сравниваются:
    иначе «Социальный вклад» 19 % сравнивался бы с обычным вкладом.
    """
    from .availability import LNR
    from .market import RATED

    results: list[Comparison] = []
    for row in rows:
        own = row.product
        if row.own.code != LNR or own.category not in RATED:
            continue
        for bank, cell in row.cells.items():
            twin = cell.product
            if twin is None or not cell.close or cell.status is None or cell.status.code != LNR:
                continue
            # Ставки нет ни у одного (дебетовые карты, платёжный счёт) —
            # сравнивать в светофоре нечего, пара остаётся в своде по ЛНР.
            if all(getattr(x, a, None) is None for x in (own, twin)
                   for a in ("rate_min", "rate_max")):
                continue
            comparison = Comparison(
                pair_id=f"{getattr(twin, 'url_path', '') or twin.title}→"
                        f"{getattr(own, 'url_path', '') or own.title}",
                label=own.title,
                category=own.category or twin.category,
                psb=twin,
                sber=own,
            )
            comparison.notes.append(f"Аналог по сути у банка {bank}: «{twin.title}»")
            mine, theirs = conditions.kind_of(own)[0], conditions.kind_of(twin)[0]
            if conditions.same_kind(mine) != conditions.same_kind(theirs):
                comparison.notes.append(
                    f"Тип ставки разный: у Сбера — {conditions.LABELS[mine]}, "
                    f"у банка — {conditions.LABELS[theirs]}")
            _evaluate(comparison, thresholds)
            results.append(comparison)

    results.sort(key=lambda c: ({RED: 0, YELLOW: 1, GREEN: 2, GREY: 3}[c.light], c.label))
    return results


def _evaluate(comparison: Comparison, thresholds: Thresholds) -> None:
    """Считает дельту и красит светофор."""
    psb, sber = comparison.psb, comparison.sber

    if psb is None or sber is None:
        comparison.light = GREY
        comparison.reason = "Нет пары для сравнения"
        return

    # Какую границу диапазона сравнивать — не формальность.
    # Кредит банк рекламирует как «ставка ОТ 16,9%», вклад — как «ДО 13,8%».
    # Клиент сравнивает именно эти витринные цифры, поэтому по кредитам берём
    # нижнюю границу, по сберегательным продуктам — верхнюю.
    higher_better = comparison.category in HIGHER_IS_BETTER
    bound = "rate_max" if higher_better else "rate_min"

    psb_rate = getattr(psb, bound)
    sber_rate = getattr(sber, bound)

    # Если нужной границы нет, откатываемся на доступную: одна цифра лучше,
    # чем серый прочерк.
    if psb_rate is None:
        psb_rate = psb.rate_min if higher_better else psb.rate_max
    if sber_rate is None:
        sber_rate = sber.rate_min if higher_better else sber.rate_max

    comparison.psb_rate = psb_rate
    comparison.sber_rate = sber_rate
    comparison.rate_bound = "max" if higher_better else "min"

    if psb_rate is None or sber_rate is None:
        comparison.light = GREY
        missing = "конкурента" if psb_rate is None else "Сбера"
        comparison.reason = f"Не удалось извлечь ставку {missing}"
        return

    delta = round(sber_rate - psb_rate, 3)
    comparison.delta_rate = delta

    if psb.apr_min is not None and sber.apr_min is not None:
        comparison.delta_apr = round(sber.apr_min - psb.apr_min, 3)

    # advantage > 0 означает «Сбер выгоднее клиенту»
    advantage = delta if higher_better else -delta

    if abs(delta) < thresholds.parity:
        comparison.light = YELLOW
        comparison.reason = f"Разница {pp(abs(delta))} — в пределах паритета"
    elif advantage > 0:
        comparison.light = GREEN
        comparison.reason = f"Сбер выгоднее клиенту на {pp(abs(delta))}"
    elif abs(delta) >= thresholds.loss:
        comparison.light = RED
        comparison.reason = f"Проигрываем конкуренту {pp(abs(delta))}"
    else:
        comparison.light = YELLOW
        comparison.reason = f"Небольшое отставание — {pp(abs(delta))}"

    if higher_better:
        comparison.notes.append(
            "Сберегательный продукт: сравниваем максимальную ставку, "
            "выгода клиента — ставка выше"
        )


def summarize(comparisons: list[Comparison]) -> dict[str, int]:
    counts = {GREEN: 0, YELLOW: 0, RED: 0, GREY: 0}
    for c in comparisons:
        counts[c.light] += 1
    return counts
