"""Сопоставление продуктов и расчёт светофора.

Главное правило модуля: сравниваются только пары, подтверждённые вручную
в config/product_map.yaml. Автоматический матчинг по названию здесь есть,
но он работает исключительно как подсказка — формирует файл предложений
для человека и никогда не попадает в отчёт сам по себе.

Причина простая: «Кредит наличными» ПСБ и «Потребительский кредит» Сбера
похожи по названию, но могут отличаться по условиям допуска. Ошибка в
такой паре — это неверная цифра в отчёте у руководителя.

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
from difflib import SequenceMatcher
from typing import Any, Iterable

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


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_title(a), normalize_title(b)).ratio()


# --- сопоставление --------------------------------------------------------

def suggest_pairs(psb_products: Iterable[Any], sber_products: Iterable[Any],
                  *, threshold: float = 0.55) -> list[dict[str, Any]]:
    """Черновые пары для ручной проверки. В отчёт не идут.

    Возвращает список кандидатов, отсортированный по убыванию похожести,
    чтобы человеку было быстрее подтверждать сверху вниз.
    """
    sber_list = list(sber_products)
    suggestions: list[dict[str, Any]] = []

    for psb in psb_products:
        scored = sorted(
            ((similarity(psb.title, s.title), s) for s in sber_list),
            key=lambda x: x[0], reverse=True,
        )
        best = [(score, s) for score, s in scored[:3] if score >= threshold]
        if not best:
            continue
        suggestions.append({
            "psb_key": getattr(psb, "url_path", psb.title),
            "psb_title": psb.title,
            "category": psb.category,
            "candidates": [
                {"sber_key": getattr(s, "product_key", s.title),
                 "sber_title": s.title,
                 "score": round(score, 3)}
                for score, s in best
            ],
        })

    suggestions.sort(key=lambda x: x["candidates"][0]["score"], reverse=True)
    return suggestions


def _index(products: Iterable[Any], key_attr: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for p in products:
        key = getattr(p, key_attr, "") or p.title
        out[str(key)] = p
        # Второй ключ — по названию: в мэппинге удобнее писать человеческое имя.
        out.setdefault(normalize_title(p.title), p)
    return out


def build_comparisons(competitor_products: Iterable[Any], sber_products: Iterable[Any],
                      pairs: list[dict[str, Any]], thresholds: Thresholds,
                      *, competitor_code: str = "") -> list[Comparison]:
    """Строит строки отчёта строго по подтверждённым парам из конфига.

    `competitor_code` отбирает пары нужного банка: в product_map.yaml
    лежат пары ко всем конкурентам сразу, и смешивать их в одном отчёте
    нельзя — ставка ВТБ в строке про ПСБ была бы прямой ошибкой.
    """
    psb_index = _index(competitor_products, "url_path")
    sber_index = _index(sber_products, "product_key")

    results: list[Comparison] = []

    for pair in pairs:
        if competitor_code and str(pair.get("bank", "psb")) != competitor_code:
            continue
        psb_key = str(pair.get("competitor") or pair.get("psb") or "")
        sber_key = str(pair.get("sber") or "")
        label = pair.get("label") or psb_key or sber_key
        category = pair.get("category") or ""

        psb = psb_index.get(psb_key) or psb_index.get(normalize_title(psb_key))
        sber = sber_index.get(sber_key) or sber_index.get(normalize_title(sber_key))

        comparison = Comparison(
            pair_id=f"{psb_key}→{sber_key}",
            label=label,
            category=category or (psb.category if psb else ""),
            psb=psb,
            sber=sber,
        )

        if psb is None:
            comparison.notes.append(
                f"В данных конкурента не найден продукт «{psb_key}»")
        if sber is None:
            comparison.notes.append(f"В выгрузке Сбера не найден продукт «{sber_key}»")

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
