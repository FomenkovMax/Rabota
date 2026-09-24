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

from .base import registry
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
class SberAdapter(SiteAdapter):
    code = "sber"
    title = "Сбер"
    strategy = "браузер: сайт показывает JS-проверку до содержимого"
    protection = "JS-челлендж F5 (переменная bobcmn в ответе)"
    verified = False

    sections = (
        ("https://www.sberbank.ru/ru/person/contributions", "Вклады"),
        ("https://www.sberbank.ru/ru/person/contributions/savings", "Накопительные счета"),
        ("https://www.sberbank.ru/ru/person/credits/money", "Кредиты"),
        ("https://www.sberbank.ru/ru/person/credits/home", "Ипотека"),
        ("https://www.sberbank.ru/ru/person/bank_cards/credit", "Кредитные карты"),
        ("https://www.sberbank.ru/ru/person/bank_cards/debit", "Дебетовые карты"),
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
