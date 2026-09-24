"""Адаптеры Сбера, ВТБ, ГенБанка и ЦМР.

Все четверо читаются браузером. Разница между ними — адреса разделов и
то, какую проверку сайт показывает до содержимого.

Про `verified`. Отмечен только ЦМР: его страницу вкладов удалось открыть
и снять с неё ставки. Остальные три написаны по разобранной структуре
сайтов, но их сбор не подтверждён на живых данных — в окружении, где
писался код, проверки Сбера и ГенБанка не проходили из-за прокси. Пока
проверка не сделана на рабочей машине, отчёт честно помечает такие
данные как неподтверждённые. Снимать флаг следует только после того, как
`python run.py check-bank <код>` отработает успешно.
"""

from __future__ import annotations

import re

from .base import registry
from .crawl_adapter import CrawlAdapter
from .site_adapter import SiteAdapter


@registry.register
class CmrAdapter(SiteAdapter):
    code = "cmr"
    title = "ЦМР"
    strategy = "обычный сайт, чтение отрисованной страницы"
    protection = ""
    verified = True

    sections = (
        ("https://cmrbank.ru/person/person-deposit/", "Вклады"),
        ("https://cmrbank.ru/person/person-deposit/deposit-calc/", "Вклады"),
        ("https://cmrbank.ru/person/person-loans/", "Кредиты"),
        ("https://cmrbank.ru/person/card/", "Банковские карты"),
    )


@registry.register
class SberAdapter(CrawlAdapter):
    """Сбер: обход розницы по ссылкам, условия — со страницы каждого продукта.

    Витрины Сбера показывают ставку не у всех продуктов: у кредитов на
    карточке только сумма и срок. Поэтому с витрин собираются ссылки, а
    условия берутся со страницы продукта; ставка с карточки витрины —
    запасная, с пометкой источника.
    """

    code = "sber"
    title = "Сбер"
    strategy = "браузер: обход витрин и страниц продуктов"
    protection = "JS-челлендж F5 (переменная bobcmn в ответе)"
    verified = False

    base_url = "https://www.sberbank.ru"
    seeds = (
        "https://www.sberbank.ru/ru/person/contributions",
        "https://www.sberbank.ru/ru/person/contributions/savings",
        "https://www.sberbank.ru/ru/person/credits/money",
        "https://www.sberbank.ru/ru/person/credits/home",
        "https://www.sberbank.ru/ru/person/bank_cards/credit",
        "https://www.sberbank.ru/ru/person/bank_cards/debit",
    )
    families = (
        ("/ru/person/contributions/savings", "Накопительные счета"),
        ("/ru/person/contributions", "Вклады"),
        ("/ru/person/credits/home", "Ипотека"),
        ("/ru/person/credits", "Кредиты"),
        ("/ru/person/bank_cards/credit", "Кредитные карты"),
        ("/ru/person/bank_cards/debit", "Дебетовые карты"),
        ("/ru/person/bank_cards", "Банковские карты"),
    )
    # Служебное внутри розничных разделов: из меню Сбера это «Полезное» —
    # калькуляторы, вопросы, налоги, уведомления, компенсации, выплаты АСВ,
    # сейфы, номинальный счёт, ИИ-помощник, кредитная история. Акции
    # собираются отдельно и в каталог продуктов не идут.
    skip = re.compile(
        r"(calc|kalkul|faq|question|vopros|help|pomosh|nalog|tax|notif|uvedoml|"
        r"compens|kompens|asv|safe|seif|sejf|nominal|assistant|gigachat|/ai\b|"
        r"podderzh|support|potencial|potential|history|istori|archive|arhiv|"
        r"document|dokument|tarif|stavki|prolong|prodlen|instruction|how_to|"
        r"article|news|blog|promo|akci|action)",
        re.I,
    )


@registry.register
class VtbAdapter(SiteAdapter):
    code = "vtb"
    title = "ВТБ"
    strategy = "браузер: условия подгружаются скриптами после загрузки"
    protection = "одностраничное приложение, контент приходит отдельными запросами"
    verified = False

    sections = (
        ("https://www.vtb.ru/personal/vklady-i-scheta/", "Вклады"),
        ("https://www.vtb.ru/personal/vklady-i-scheta/nakopitelnyi-schet/", "Накопительные счета"),
        ("https://www.vtb.ru/personal/kredit/", "Кредиты"),
        ("https://www.vtb.ru/personal/ipoteka/", "Ипотека"),
        ("https://www.vtb.ru/personal/karty/kreditnye/", "Кредитные карты"),
        ("https://www.vtb.ru/personal/karty/debetovye/", "Дебетовые карты"),
    )


@registry.register
class GenbankAdapter(SiteAdapter):
    code = "genbank"
    title = "ГенБанк"
    strategy = "браузер: сайт закрыт JS-проверкой"
    protection = "Qrator: ответ 401 и скрипт qauth.js до выдачи содержимого"
    verified = False

    sections = (
        ("https://genbank.ru/personal/deposits/", "Вклады"),
        ("https://genbank.ru/personal/credits/", "Кредиты"),
        ("https://genbank.ru/personal/cards/", "Банковские карты"),
    )
