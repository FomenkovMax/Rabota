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
        # Сбор 27.10.2026: ещё посадочные страницы карт — заняли 16 из 80
        # страниц лимита, и до IT-, военной и сельской ипотеки обход не
        # дошёл. Погашение, страховщики и доверенности — не продукты.
        r"|^/ru/person/bank_cards/credit_cards/(?:dlya-pokupok|za-15-minut|"
        r"s[-_]dostavkoj[-_]na[-_]dom|cashback|s-nizkim-proczentom|"
        r"s-momentalnym-resheniyem|srochno|ehkspress-kreditnye-karty)/?$"
        # Сбор 28.10.2026: «Кредитная карта в Архангельске/Белгороде/…» по
        # адресам /credit_cards/arhangelsk и т. п. — городов не перечислить,
        # поэтому наоборот: продукты Сбера — только СберКарты, остальное
        # в этом разделе — посадочные страницы.
        r"|^/ru/person/bank_cards/credit_cards/"
        r"(?!credit_sberkarta|molodezhnaya|dlya-studentov)[\w-]+/?$"
        r"|^/ru/person/bank_cards/debit/(?:besplatnaya-karta-mir|v-[\w-]+|dlya-vkladov|"
        r"dlya-perevodov|dlya-pokupok|cashback|besplatnoe_obsluzhivanie)/?$"
        r"|^/ru/person/credits/(?:repayment|insurance)/?$"
        r"|^/ru/person/contributions/poa/?$"
    ),
    "tbank.ru": re.compile(
        r"^/loans/cash-loan/(?:na-[\w-]+|pensioneram|studentam|selfemployed|"
        r"nizkij-proczent|srochnyj-kredit-nalichnymi|nopledge|how-repay|form/[\w-]+)/?$"
        # Сбор 28.10.2026: автокредит «на Lada / Haval / …», подборки вкладов
        # «на 3 месяца / для пенсионеров / в рублях», посадочные кредитных
        # карт («без процентов», «по паспорту», «за 5 минут»…) — копии продуктов.
        r"|^/loans/auto-loan/[\w-]+-v-kredit/?$"
        r"|^/savings/deposit/(?:vklad[\w-]*|vklady[\w-]*|dolgosrochnyi-vklad)/?$"
        r"|^/cards/credit-cards/(?:without-[\w-]+|ot-5-minut|v-den-[\w-]+|po-pasportu|"
        r"home-delivery|cashback|virtual-credit-card|with-[\w-]+|shopping|travel|driver|"
        r"games)/?$"
        # «Дебетовая карта Black в Москве / Уфе / …» (сбор 28.10.2026) — города.
        r"|^/cards/debit-cards/tinkoff-black/(?!pension|junior|selfemployed|mir|youth-card)"
        r"[\w-]+/?$"
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
        r"|^/personal/karty/kreditnye/(?:s-[\w-]+|v-den-[\w-]+|\d+|po-pasportu|"
        r"lipeck|habarovsk|balashiha)/?$"
        # Сбор 28.10.2026: подборки и города среди дебетовых карт и кредитов.
        r"|^/personal/karty/debetovye/(?:s-[\w-]+|debetovaya-karta-[\w-]+|momentalnye|"
        r"karty-s-[\w-]+|imennye|digital-designs|balashiha|lipeck|v-valyute)/?$"
        r"|^/personal/kredit/(?:spb|srochnyj|nizkaya-stavka|online|nalichnymi/[\w-]+)/?$"
    ),
}


def is_seo_page(url: str) -> bool:
    """Адрес — SEO-копия продукта, а не сам продукт."""
    parts = urlsplit(url or "")
    host = parts.netloc.lower().removeprefix("www.")
    pattern = _SEO_PAGES.get(host)
    return bool(pattern and pattern.search(parts.path))
