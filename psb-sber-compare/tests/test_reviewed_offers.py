from datetime import datetime, timedelta
from pathlib import Path

from src.current_offers import MOSCOW, active_promo, rankings
from src.reviewed_offers import load


def test_reviewed_terms_keep_regions_contract_days_and_original_dates():
    path = Path(__file__).resolve().parents[1] / "config" / "evidence" / "retail-2026-11-19.json"
    banks = ["Сбер", "ПСБ", "ВТБ", "Т-Банк", "РостФинанс", "ЦМР", "Генбанк"]
    now = datetime(2026, 11, 19, 12, tzinfo=MOSCOW)
    products, statuses, promos = load(path, banks, now.date())
    assert {p.bank for p in products} == set(banks)
    for region, psb_count, promo_count in (("lnr", 1, 2), ("lugansk", 0, 1)):
        offers = rankings(products, statuses, banks, region=region, now=now, hours=72,
                          key_rate=14, region_methods={})
        assert offers["Вклады"]["checked"] == 0
        assert offers["Вклады на 367 дней"]["checked"] == psb_count
        assert [(p.bank, p.value) for p in offers["Вклады на 370 дней"]["leaders"]] == [
            ("ВТБ", 55753.42)
        ]
        assert sum(active_promo(p, region=region, now=now, hours=24) for p in promos) == promo_count
        expired = rankings(products, statuses, banks, region=region,
                           now=now + timedelta(hours=73), hours=72, key_rate=14,
                           region_methods={})
        assert all(offer["checked"] == 0 for offer in expired.values())
        assert not any(active_promo(p, region=region, now=now + timedelta(hours=25), hours=24)
                       for p in promos)
