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
        # Проверено по обходу 06.10.2026: /contributions/savings отдаёт 404,
        # а /credits/homenew — витрина всех ипотечных программ.
        "https://www.sberbank.ru/ru/person/contributions/deposits",
        "https://www.sberbank.ru/ru/person/credits/money",
        "https://www.sberbank.ru/ru/person/credits/homenew",
        "https://www.sberbank.ru/ru/person/bank_cards/credit_cards",
        "https://www.sberbank.ru/ru/person/bank_cards/debit",
    )
    # Главные продукты для сравнения — их адреса видны в обходе 06.10.2026.
    # Сбер пускает около 30 страниц за сеанс, поэтому они идут первыми.
    priority = (
        "https://www.sberbank.ru/ru/person/bank_cards/debit/sberkarta",
        "https://www.sberbank.ru/ru/person/bank_cards/credit_cards/credit_sberkarta",
        "https://www.sberbank.ru/ru/person/credits/home/family",
        "https://www.sberbank.ru/ru/person/credits/money/consumer_unsecured",
        "https://www.sberbank.ru/ru/person/credits/money/consumer_refinance",
        "https://www.sberbank.ru/ru/person/credits/money/avtokredit",
        "https://www.sberbank.ru/ru/person/credits/home/buying_project",
        "https://www.sberbank.ru/ru/person/credits/home/buying_complete_house",
        "https://www.sberbank.ru/ru/person/contributions/deposits/vklad/vklad_luchshiy_procent",
        "https://www.sberbank.ru/ru/person/contributions/deposits/vklad_kluchevoy",
        "https://www.sberbank.ru/ru/person/contributions/deposits/nakopi",
    )
    # Порядок важен: точный префикс раньше общего.
    families = (
        ("/ru/person/contributions/deposits/nakopi", "Накопительные счета"),
        ("/ru/person/credits/homenew", "Ипотека"),
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
        r"article|news|blog|promo|akci|action|"
        # Рекламные дубли одного продукта: «кредит на 50 000 рублей», «на 2
        # года», «с 18 лет», «в Казани», «без справок», «по паспорту»… В
        # первом сборе они съели половину лимита страниц, а до семейной
        # ипотеки и кредитных карт обход так и не дошёл.
        r"[/_-]na[_-]\d|rublej|/s[_-]\d+[_-](let|goda)|/kredit[_-]s[_-]|/\d+[_-]dn|"
        r"/s[_-]limitom|/kreditnaya-karta-\d|-million|"
        r"/(sankt-peterburg|novosibirsk|ekaterinburg|kazan|nizhny-novgorod|"
        r"chelyabinsk|samara|omsk|perm|ufa|rostov-na-donu|krasnoyarsk|voronezh|"
        r"volgograd|moskva|krasnodar|saratov|tyumen|izhevsk|barnaul|irkutsk)\b|"
        r"/vklad-v-|/bez-|/bez_|/po-pasportu|/na-kartu|/v-den-|/na-otpusk|"
        r"/credit-na-svadbu|/na-telefon|/na-lecheniye|/tehnika$|/remont$|"
        r"/necelevoy|/na-pokupku|/ekspress|/dlya-samozanyat|/dlya_samozanyat|"
        r"/gallery|/izmenenie|onlajn-zayavka|/design_konstructor|/services/)",
        re.I,
    )


@registry.register
class VtbAdapter(CrawlAdapter):
    """ВТБ: обход розницы по ссылкам, как у Сбера.

    По спецификации у ВТБ есть отдельная ипотека для новых регионов —
    её страница в главных продуктах. Регион на сайте выбирается, поэтому
    без куки региона (banks.vtb.region_cookies) условия будут не ЛНР и в
    сравнение не пойдут.
    """

    code = "vtb"
    title = "ВТБ"
    strategy = "браузер: обход витрин и страниц продуктов"
    protection = "не проверено"
    verified = False

    base_url = "https://www.vtb.ru"
    seeds = (
        "https://www.vtb.ru/personal/vklady-i-scheta/",
        "https://www.vtb.ru/personal/kredit/",
        "https://www.vtb.ru/personal/ipoteka/",
        "https://www.vtb.ru/personal/karty/kreditnye/",
        "https://www.vtb.ru/personal/karty/debetovye/",
    )
    priority = (
        "https://www.vtb.ru/personal/ipoteka/new-regions/",
        "https://www.vtb.ru/personal/vklady-i-scheta/nakopitelnyi-schet/",
    )
    families = (
        ("/personal/vklady-i-scheta/nakopitelnyi-schet", "Накопительные счета"),
        ("/personal/vklady-i-scheta", "Вклады"),
        ("/personal/ipoteka", "Ипотека"),
        ("/personal/kredit", "Кредиты"),
        ("/personal/karty/kreditnye", "Кредитные карты"),
        ("/personal/karty/debetovye", "Дебетовые карты"),
        ("/personal/karty", "Банковские карты"),
    )
    family_words = ()
    skip = re.compile(
        r"(calc|kalkul|faq|question|vopros|help|pomosh|nalog|tax|document|dokument|"
        r"tarif|archive|arhiv|news|blog|promo|akci|action|business|biz|/legal|"
        r"[/_-]na[_-]\d|rublej|/(moskva|sankt-peterburg|novosibirsk|ekaterinburg|kazan)\b|"
        r"/bez-|/dlya-|/onlajn-zayavka|/form\b|/anketa)", re.I)


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


#: Разделы розницы по словам в адресе — для сайтов, структуру которых мы ещё
#: не разбирали. Порядок важен: «кредитная карта» раньше «кредита» и «карты».
RETAIL_WORDS: tuple[tuple[str, str], ...] = (
    # Вклад раньше «savings»: у Т-Банка вклад живёт по адресу /savings/deposit.
    (r"vklad|deposit", "Вклады"),
    (r"nakopit|savings|saving-account", "Накопительные счета"),
    (r"ipotek|mortgage", "Ипотека"),
    (r"credit[-_]?card|kreditn\w*[-_]kart", "Кредитные карты"),
    (r"debit|debet", "Дебетовые карты"),
    (r"kredit|credit|loan|zaim|zaym", "Кредиты"),
    (r"/cards?\b|/kart", "Банковские карты"),
)

#: Не розница для физлиц и не продукты: бизнес, документы, новости, помощь.
NOT_RETAIL = re.compile(
    r"(business|biz|/corp|corporate|/legal|/yur|/msb|/sme|/ip/|partner|investor|"
    r"about|news|press|career|vacanc|help|faq|support|document|tarif|"
    r"calc|kalkul|promo|akci|blog|journal|/media|login|auth)",
    re.I,
)


@registry.register
class TbankAdapter(CrawlAdapter):
    """Т-Банк: условия едины по РФ (подтвердил заказчик 07.10.2026).

    Офисов в ЛНР у банка нет, обслуживание онлайн. Структуру сайта мы ещё
    не разбирали, поэтому раздел определяется по словам в адресе; после
    первой проверки (check-bank tbank) сюда лягут точные витрины.
    """

    code = "tbank"
    title = "Т-Банк"
    strategy = "браузер: обход витрин и страниц продуктов"
    protection = "не проверено"
    verified = False

    base_url = "https://www.tbank.ru"
    # Главные продукты — по обходу 07.10.2026; иначе лимит уходит на
    # рекламные копии карты Black («для студентов», «именная»…).
    priority = (
        "https://www.tbank.ru/cards/debit-cards/tinkoff-black/",
        "https://www.tbank.ru/cards/credit-cards/tinkoff-platinum/",
        "https://www.tbank.ru/loans/cash-loan/",
        "https://www.tbank.ru/loans/refinance/",
        "https://www.tbank.ru/loans/auto-loan/",
        "https://www.tbank.ru/savings/deposit/",
        "https://www.tbank.ru/savings/saving-account/",
        "https://www.tbank.ru/cards/debit-cards/tinkoff-black/pension/",
    )
    seeds = (
        "https://www.tbank.ru/",
        "https://www.tbank.ru/cards/debit-cards/",
        "https://www.tbank.ru/cards/credit-cards/",
        "https://www.tbank.ru/loans/",
        "https://www.tbank.ru/mortgage/",
        "https://www.tbank.ru/savings/",
    )
    family_words = RETAIL_WORDS
    skip = re.compile(NOT_RETAIL.pattern + "|" + (
        r"/city/|/foreign|/form$|/(dlya|bez|s)-|virtualnaya|beskontaktnaya|"
        r"nakopitelnaya-karta|mezhdunarodnaya|imennaya|besplatnaya|momentalnaya|"
        r"/debit-cards/(premium|travel|driver|games|shopping)$|insurance"), re.I)


@registry.register
class RostfinanceAdapter(CrawlAdapter):
    """РостФинанс — сайт https://www.rostfinance.ru/ (дал заказчик 07.10.2026).

    Структуру сайта мы ещё не видели: обход начинается с главной, раздел
    определяется по словам в адресе. После первой проверки
    (check-bank rostfinance) сюда лягут точные витрины.
    """

    code = "rostfinance"
    title = "РостФинанс"
    strategy = "браузер: обход витрин и страниц продуктов"
    protection = "не проверено"
    verified = False

    base_url = "https://www.rostfinance.ru"
    # Без «/» в конце адреса сайт отдаёт 404 (обход 07.10.2026).
    keep_slash = True
    seeds = (
        "https://www.rostfinance.ru/",
        "https://www.rostfinance.ru/deposits/",
        "https://www.rostfinance.ru/credit/",
        "https://www.rostfinance.ru/mortgage/",
        "https://www.rostfinance.ru/cards/",
    )
    family_words = RETAIL_WORDS
    skip = NOT_RETAIL
