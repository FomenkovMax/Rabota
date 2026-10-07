"""SEO-страницы банков не считаются продуктами."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from src.banks.seo import is_seo_page


@pytest.mark.parametrize("url", [
    "https://www.psbank.ru/personal/loans/kredit-100000-rubley",
    "https://www.psbank.ru/personal/loans/kredit-po-pasportu",
    "https://www.psbank.ru/personal/creditcards/limit-50000-rub",
    "https://www.psbank.ru/personal/saving/vklady-s-vysokimi-procentami",
    "https://www.tbank.ru/loans/cash-loan/na-iphone",
    "https://www.tbank.ru/loans/cash-loan/pensioneram",
    "https://www.vtb.ru/personal/ipoteka/dlja-pensionerov",
    "https://www.vtb.ru/personal/ipoteka/mashinomesta-i-kladovki",
    "https://www.vtb.ru/personal/ipoteka/anapa",
    "https://www.vtb.ru/personal/ipoteka/medikam",
    "https://www.sberbank.ru/ru/person/contributions/deposits/schet-v-moskve",
    "https://www.sberbank.ru/ru/person/contributions/deposits/vklad-ot-100000-rubley",
    "https://www.sberbank.ru/ru/person/contributions/accounts/candidate",
])
def test_seo_pages(url):
    assert is_seo_page(url)


@pytest.mark.parametrize("url", [
    "https://www.psbank.ru/personal/loans/kredit-nalichnymi",
    "https://www.psbank.ru/personal/loans/refinancing",
    "https://www.psbank.ru/personal/creditcards/100_plus",
    "https://www.psbank.ru/personal/saving/dragotsennyj",
    "https://www.tbank.ru/loans/cash-loan",
    "https://www.tbank.ru/loans/cash-loan/realty",
    "https://www.tbank.ru/loans/cash-loan/auto",
    "https://www.vtb.ru/personal/ipoteka/new-regions",
    "https://www.vtb.ru/personal/ipoteka/selskaya",
    "https://www.vtb.ru/personal/kredit/nalichnymi",
    "https://www.sberbank.ru/ru/person/credits/money",
    "https://www.sberbank.ru/ru/person/contributions/deposits/nakopi",
    "https://www.sberbank.ru/ru/person/contributions/deposits/vklad/vklad_luchshiy_procent",
    "https://www.vtb.ru/personal/ipoteka/combo",
])
def test_real_products_stay(url):
    assert not is_seo_page(url)
