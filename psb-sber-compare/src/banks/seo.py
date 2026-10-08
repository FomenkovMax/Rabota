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
    # Сбор 07.10.2026: «Накопительный счёт в Москве/Казани/…», «Вклад от
    # 100 000 рублей», «Срочные вклады» — подборки и города; спецсчета
    # (избирательный, участника закупок, «С», «Амана», текущий) — не
    # сберегательные продукты для сравнения.
    "sberbank.ru": re.compile(
        r"^/ru/person/contributions/deposits/(?:schet-v-[\w-]+|vklad-na-mesyac|"
        r"vklad-ot-\d+-rubley|vklad-s-ezhemesyachnoy-kapitalizaciey|"
        r"vklady-(?:dolgosrochnye|kratkosrochnye|s-ezhemesyachnymi-vyplatami)|"
        r"srochnyy-vklad|schet-tipa-c|schyot_amana|tec)/?$"
        r"|^/ru/person/contributions/accounts/(?:candidate|special)/?$"
        # Сбор 09.10.2026: посадочные страницы кредитов и кредитных карт,
        # тарифы и взыскание — не продукты.
        r"|^/ru/person/contributions/deposits/(?:vklad-\d+-rubley|vklad_dlya-zarplatnikov)/?$"
        r"|^/ru/person/credits/money/(?:dengi-do-zarplaty|dlya_molodezhi|na_kartu|"
        r"po_pasportu)/?$"
        r"|^/ru/person/credits/(?:kredit|collection/[\w-]+)/?$"
        r"|^/ru/person/bank_cards/credit_cards/(?:dlya_puteshestvij|luchshaya|mir|"
        r"momentalnye_po_pasportu|rassrochka|s_beplatnym_obsluzhivaniyem|"
        r"s_bolshojt_kreditnojt_nagruzkoj|za_5_minut|grace|s_lgotnym_periodom)/?$"
    ),
    "tbank.ru": re.compile(
        r"^/loans/cash-loan/(?:na-[\w-]+|pensioneram|studentam|selfemployed|"
        r"nizkij-proczent|srochnyj-kredit-nalichnymi|nopledge)/?$"
    ),
    "vtb.ru": re.compile(
        r"^/personal/ipoteka/(?:dlja-[\w-]+|mnogodetnym|ipoteka-s-pervym-vznosom|"
        r"s-annuitetnymi-platezhami|online|mashinomesta-i-kladovki|"
        r"kreditovanie-inostrannyh-grazhdan|materi-odinochke|medikam|na-dvoih|"
        r"studentam|ocenka-zhilya|stavki-po-ipoteke|"
        # Города (сбор 07.10.2026): условия общие, страница — посадочная.
        r"anapa|balashiha|domodedovo|elektrostal|habarovsk|kolomna|korolyov|krym|"
        r"lipeck|maykop|nizhnij-novgorod|orehovo-zuevo|prokopevsk|sergiev-posad|"
        r"tyva)/?$"
        r"|^/personal/karty/kreditnye/(?:s-[\w-]+|v-den-[\w-]+)/?$"
    ),
}


def is_seo_page(url: str) -> bool:
    """Адрес — SEO-копия продукта, а не сам продукт."""
    parts = urlsplit(url or "")
    host = parts.netloc.lower().removeprefix("www.")
    pattern = _SEO_PAGES.get(host)
    return bool(pattern and pattern.search(parts.path))
