"""ЦМР: условия из блоков данных в коде страниц (страницы с сайта 07.10.2026, сокращены)."""

from __future__ import annotations

from src.banks import cmr

DEPOSIT_PAGE = """<div>{{ deposit.name }}</div><script>
var app = {deposites: {"21":{"id":"21","name":"Вклад \\"Доход на максимум\\"","type":"deposit",
"is_active":"1","max_sum":500000,"annotation":"Вклад с максимальной доходностью",
"rates":{"85":{"replenish":null,"withdraw":null,
 "pct_at_month":{"salary_card_disable":[null,12.9,12.7],"salary_card_on":{"1":13.0},"salary_card_off":{"1":12.8}},
 "pct_at_and":{"salary_card_disable":[],"salary_card_on":{"1":14.95},"salary_card_off":{"1":14.75,"2":13.2}}}},
"terms":{"1":91,"2":181},"sums":{"85":10000}},
"27":{"id":"27","name":"Накопительный счет \\"Больше чем счет\\"","type":"account","is_active":"1",
"max_sum":0,"rates":{"94":{"replenish":true,"withdraw":true,
 "pct_at_month":{"salary_card_disable":{"156":13.5},"salary_card_on":[],"salary_card_off":[]},
 "pct_at_and":{"salary_card_disable":{"156":""},"salary_card_on":[],"salary_card_off":[]}}},
"terms":{"156":31},"sums":{"94":1}}},
other: 1};
</script>"""

CREDIT_PAGE = """<div>Главная страница / Частным клиентам / Кредиты / Рефинансирование</div>
<script>var s = {credit: {"id":"15","name":"Рефинансирование","min_term":12,"max_term":60,
"min_sum":100000,"max_sum":3000000,"rates":{"default":[[29.9]],"salary_discount":[[29.9]]},
"dscr":"Кредит на рефинансирование"}, x: 1};</script>
<p>Ставки по кредиту:</p><p>Полная стоимость кредита 27,863% - 33,889%</p>
<p>Процентные ставки:</p><p>27,9 % годовых – для клиентов, получающих зарплату на карту Банка</p>
<p>29,9 % годовых – для остальных категорий клиентов</p>"""

CARD_PAGE = """<div>Главная страница / Частным клиентам / Карты / Карта ЦМР.Драйв</div>
<p>Начисление процентов на остаток:</p>
<p>10% годовых, на сумму остатка до 100 000 рублей, в случае оплаты более 20 000 рублей</p>
<p>Кешбэк 5% при оплате товаров/услуг в категории «Автоуслуги»</p>
<p>Выдача наличных: без комиссии до 500 000 рублей в месяц</p>"""


def test_deposits_come_from_embedded_data():
    data = cmr.embedded_json(DEPOSIT_PAGE, "deposites")
    products = [cmr.deposit_product(item, region="ЛНР", now="") for item in data.values()]
    deposit, account = products
    assert deposit.title == "Вклад «Доход на максимум»" and deposit.category == "Вклады"
    # 14,95 % — только с зарплатной картой ЦМР: в общий ряд идёт лучшая
    # ставка без неё, а эта — отдельной строкой (аудит 07.10.2026).
    assert (deposit.rate_min, deposit.rate_max) == (12.7, 14.75)
    assert deposit.terms["Ставка с зарплатной картой"].startswith("до 14,95 %")
    assert "с зарплатной картой ЦМР" not in deposit.rate_conditions
    # Ставки по срокам — без зарплатной карты: 91 дн. 14,75 %, 181 дн. 13,2 %.
    assert deposit.terms["Ставки по срокам"] == "91 дн. — 14,75 %; 181 дн. — 13,2 %"
    assert (deposit.amount_min, deposit.amount_max) == (10000, 500000)
    assert account.category == "Накопительные счета" and account.rate_max == 13.5
    assert account.terms["Пополнение"] == "да"


def test_credit_rate_from_data_and_text():
    product = cmr.credit_product(CREDIT_PAGE, "https://cmrbank.ru/person/person-loans/refinancing/",
                                 region="ЛНР", now="")
    assert (product.rate_min, product.rate_max) == (27.9, 29.9)
    assert (product.apr_min, product.apr_max) == (27.863, 33.889)
    assert (product.term_min_months, product.term_max_months) == (12, 60)
    assert product.amount_max == 3000000


def test_card_balance_rate_and_fees():
    product = cmr.card_product(CARD_PAGE, "https://cmrbank.ru/person/card/drive-card/",
                               region="ЛНР", now="")
    assert product.title == "Карта ЦМР.Драйв" and product.rate_max == 10.0
    assert "Автоуслуги" in product.terms["Кешбэк"]
    assert product.terms["Снятие в чужих банкоматах"].startswith("Выдача наличных")


def test_section_links_skip_service_pages():
    page = ('<a href="/person/card/drive-card/">a</a><a href="/person/card/card-documents/">b</a>'
            '<a href="/person/card/">c</a><a href="/person/person-loans/restructuring/">d</a>')
    assert cmr.section_links(page, "/person/card/") == ["https://cmrbank.ru/person/card/drive-card/"]
