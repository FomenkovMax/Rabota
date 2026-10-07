"""SEO-страницы банков: тот же продукт под другим заголовком.

«Кредит на айфон», «Кредит 100 000 рублей», «Ипотека для пенсионеров»,
«Кредитные карты до 50 тысяч рублей» — посадочные страницы для поиска.
Условия на них общие с основным продуктом (у ВТБ все по 23,7 %), а в
отчёте они множили продукты и вылезали лучшими в программе: «Рыночная
ипотека — лучший ВТБ, „Ипотека на машино-места и кладовки“».

Список адресов составлен по сбору 07.10.2026. Основные страницы
(«Кредит наличными», «Кредит под залог», программы ипотеки) остаются.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

_SEO_PAGES = {
    "psbank.ru": re.compile(
        r"^/personal/loans/(?:kredit-\d+-rubley|kredit-bez-spravok|kredit-bez-zaloga|"
        r"kredit-na-\d+-goda|kredit-na-kartu|kredit-na-remont|kredit-na-stroitelstvo-doma|"
        r"kredit-po-\d+-dokumentam|kredit-po-pasportu|vacation)/?$"
        r"|^/personal/creditcards/limit-\d+-rub/?$"
        r"|^/personal/saving/vklady-s-vysokimi-procentami/?$"
    ),
    "tbank.ru": re.compile(
        r"^/loans/cash-loan/(?:na-[\w-]+|pensioneram|studentam|selfemployed|"
        r"nizkij-proczent|srochnyj-kredit-nalichnymi|nopledge)/?$"
    ),
    "vtb.ru": re.compile(
        r"^/personal/ipoteka/(?:dlja-[\w-]+|mnogodetnym|ipoteka-s-pervym-vznosom|"
        r"s-annuitetnymi-platezhami|online|mashinomesta-i-kladovki|"
        r"kreditovanie-inostrannyh-grazhdan)/?$"
    ),
}


def is_seo_page(url: str) -> bool:
    """Адрес — SEO-копия продукта, а не сам продукт."""
    parts = urlsplit(url or "")
    host = parts.netloc.lower().removeprefix("www.")
    pattern = _SEO_PAGES.get(host)
    return bool(pattern and pattern.search(parts.path))
