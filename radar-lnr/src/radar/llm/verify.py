"""ЖЁСТКОЕ ПРАВИЛО: ничего не выдумывать. Проверяем, что ИНН/суммы/численность реально есть в тексте поста."""
from __future__ import annotations

import re

from .schemas import Event


def inn_checksum_ok(inn: str) -> bool:
    """Контрольная сумма ИНН (10 цифр — юрлицо, 12 — ИП/физлицо)."""
    if not re.fullmatch(r"\d{10}|\d{12}", inn):
        return False
    d = [int(x) for x in inn]
    if len(d) == 10:
        w = [2, 4, 10, 3, 5, 9, 4, 6, 8]
        return sum(a * b for a, b in zip(w, d)) % 11 % 10 == d[9]
    w1 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
    w2 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
    return (sum(a * b for a, b in zip(w1, d)) % 11 % 10 == d[10]
            and sum(a * b for a, b in zip(w2, d)) % 11 % 10 == d[11])


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def numbers_in(text: str) -> set[str]:
    """Все числа из текста как целые токены: '1 500', '1,5' -> '1500', '1.5'. Без подстрок внутри чужих чисел."""
    t = re.sub(r"(?<=\d)[\s\u00a0](?=\d{3}(?!\d))", "", text)       # «1 500» -> «1500»
    return {m.replace(",", ".") for m in re.findall(r"\d+(?:[.,]\d+)?", t)}


def sanitize_event(ev: Event, source_text: str) -> Event:
    """Обнуляет всё, чего нет в исходном тексте. Возвращает исправленное событие."""
    text_nums = numbers_in(source_text)

    for org in ev.organizations:
        if org.inn_if_in_text:
            inn = _digits(org.inn_if_in_text)
            # ИНН должен стоять в тексте подряд и иметь верную контрольную сумму
            if not (inn in re.sub(r"[\s-]", "", source_text) and inn_checksum_ok(inn)):
                org.inn_if_in_text = None
            else:
                org.inn_if_in_text = inn

    # Суммы: оставляем только те, где ВСЕ числа встречаются в тексте как отдельные числа
    ev.amounts = [a for a in ev.amounts if (n := numbers_in(a)) and n <= text_nums]

    # Численность: число должно встречаться в тексте как отдельное число
    if ev.employees_mentioned is not None and str(ev.employees_mentioned) not in text_nums:
        ev.employees_mentioned = None

    # Фамилии/имена: каждое слово имени должно быть в тексте (в любой форме — проверяем корень)
    low = source_text.lower().replace("ё", "е")
    kept = []
    for p in ev.persons:
        parts = [w for w in re.split(r"\s+", p.name.lower().replace("ё", "е")) if len(w) > 2]
        if parts and all(w[: max(3, len(w) - 2)] in low for w in parts):
            kept.append(p)
    ev.persons = kept
    return ev
