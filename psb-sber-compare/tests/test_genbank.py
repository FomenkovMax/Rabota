import pytest

from src.banks.genbank import GenbankAdapter


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

