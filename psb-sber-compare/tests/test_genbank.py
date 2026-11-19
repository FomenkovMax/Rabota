import json

import pytest

from src.availability import status_of
from src.banks.genbank import (ARCHIVE_CARD, CATALOGUE_ARCHIVE, GenbankAdapter,
                               saved_catalogue_products)


@pytest.mark.parametrize("path,category", [
    ("/chastnym-litsam/cards/my-card/", "Дебетовые карты"),
    ("/chastnym-litsam/cards/moya-kreditnaya-karta/", "Кредитные карты"),
    ("/chastnym-litsam/deposits/klassicheskiy-plus/", "Вклады"),
    ("/chastnym-litsam/credit_for_clients/kredity-dlya-chastnykh-lits-/dostupnyy/", "Кредиты"),
    ("/chastnym-litsam/credit_for_clients/avtokreditovani/", "Автокредиты"),
    ("/chastnym-litsam/insurance/", "Страхование"),
    ("/chastnym-litsam/seyfovye-yacheyki/", "Сейфовые ячейки"),
    ("/chastnym-litsam/slitki-iz-zolota/", "Инвестиции"),
    ("/chastnym-litsam/monety-iz-dragotsennykh-metallov/", "Инвестиции"),
    ("/chastnym-litsam/raschetno-kassovoe-obsluzhivanie/", "Прочее"),
    ("/services/tsifrovoy-genbank/", "Прочее"),
    ("/usefull/kreditnaya-karta-eto-chto-i-kak-ey-polzovatsya/", ""),
    ("/yur-litsam/credit_for_business/", ""),
])
def test_official_genbank_navigation(path, category):
    assert GenbankAdapter(region=None)._family("https://www.genbank.ru" + path) == category


def test_official_catalogue_cards_keep_original_source_and_partial_terms(tmp_path):
    archive = tmp_path / CATALOGUE_ARCHIVE
    archive.mkdir()
    source = "https://www.genbank.ru/chastnym-litsam/deposits/"
    (archive / "manifest.json").write_text(json.dumps([{
        "url": source, "html": "catalogue.html", "saved_at": "2026-11-13T16:59:03",
    }]), encoding="utf-8")
    (archive / "catalogue.html").write_text("""
        <div class="b-product-row">
            <a href="/chastnym-litsam/deposits/klassicheskiy-plus/">
                <h2>Классический ПЛЮС</h2><div>до 13,6%</div>
            </a>
        </div>
        <div class="b-product-row">
            <a href="/chastnym-litsam/deposits/kopilka/">
                <h2>Копилка</h2><div>7%</div>
            </a>
        </div>
        <div class="b-product-row">
            <a href="https://other.example/chastnym-litsam/deposits/example/">
                <h2>Другая программа</h2>
            </a>
        </div>
    """, encoding="utf-8")

    first, second = saved_catalogue_products(tmp_path, region="Луганск")
    assert first.source_url == source + "klassicheskiy-plus/"
    assert first.terms[ARCHIVE_CARD] == source
    assert first.collected_at == "2026-11-13T16:59:03"
    assert first.rate_min is None and first.rate_max is None
    assert "до 13,6%" in first.terms["Условия на витрине"]
    assert second.category == "Накопительные счета"
    assert second.terms["Условия на витрине"] == "Копилка\n7%"
    assert not status_of(first, region_method="not_confirmed").city_confirmed
