"""Тесты разбора страниц по видимому тексту.

Разбор по тексту грубее разбора по структуре, поэтому цена ошибки здесь
выше: в отчёт может попасть строка, которая продуктом не является. Тесты
закрепляют именно те случаи, на которых наивное правило ошибалось.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from src.banks.generic_site import _is_product_title, extract_products, to_products


@pytest.mark.parametrize("line", [
    "Вклад «ЦМР Старт»",
    "Кредит наличными",
    "Дебетовая карта для автомобилистов",
    "Накопительный счёт «Копилка»",
    "Ипотека с господдержкой",
])
def test_product_titles_accepted(line):
    assert _is_product_title(line) is True


@pytest.mark.parametrize("line", [
    # Способ выплаты процентов из калькулятора — не продукт, хотя слово есть.
    "Ежемесячно на вклад",
    "Ежемесячно на счет",
    "В конце срока",
    "Процентная ставка:",
    "Пополнение",
    # Заголовок раздела перехватывал ставку у первой карточки под ним.
    "Вклады и счета",
    "Накопительные счета",
    "Кредитные карты",
    # Название документа, а не продукта.
    "Условия привлечения срочного банковского вклада",
])
def test_non_products_rejected(line):
    assert _is_product_title(line) is False


def test_rate_binds_to_nearest_product():
    text = "\n".join([
        "Вклады и счета",
        "Вклад «ЦМР Доход»",
        "Пополнение", "Нет", "Снятие",
        "До 13,8 %",
        "Вклад «ЦМР Комфорт»",
        "Пополнение", "Да", "Снятие",
        "До 13,5 %",
    ])
    found = extract_products(text)
    assert [p.title for p in found] == ["Вклад «ЦМР Доход»", "Вклад «ЦМР Комфорт»"]
    assert [p.rate_max for p in found] == [13.8, 13.5]


def test_key_rate_is_not_a_product_rate():
    """«Ключевая ставка 16,5%» — макропоказатель, а не условие вклада."""
    text = "\n".join([
        "Вклад «ЦМР Доход»",
        "Ключевая ставка 16,5%",
        "До 13,8 %",
    ])
    found = extract_products(text)
    assert len(found) == 1
    assert found[0].rate_max == 13.8


def test_one_rate_is_not_reused_by_two_products():
    """Ставка принадлежит одному продукту; вторая карточка без ставки — пустая."""
    text = "\n".join([
        "Вклад «Первый»",
        "До 13,8 %",
        "Вклад «Второй»",
        "Пополнение",
    ])
    found = extract_products(text)
    assert [p.title for p in found] == ["Вклад «Первый»"]


def test_to_products_deduplicates():
    from src.banks.generic_site import TextProduct

    items = [TextProduct(title="Вклад «А»", rate_min=10.0, rate_max=10.0),
             TextProduct(title="вклад «а»", rate_min=11.0, rate_max=11.0)]
    out = to_products(items, bank="ЦМР", category="Вклады", region="ЛНР",
                      collected_at="", source_url="https://example.ru")
    assert len(out) == 1
    assert out[0].bank == "ЦМР"
