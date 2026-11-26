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
    for region in ("lnr", "lugansk"):
        offers = rankings(products, statuses, banks, region=region, now=now, hours=72,
                          key_rate=14, region_methods={})
        assert [(p.bank, p.value) for p in offers["Вклады"]["leaders"]] == [("Т-Банк", 57500)]
        assert offers["Вклады на 367 дней"]["checked"] == 1
        assert [(p.bank, p.value) for p in offers["Вклады на 370 дней"]["leaders"]] == [
            ("ВТБ", 55753.42)
        ]
        assert offers["Кредиты"]["leaders"] == []
        assert [(p.bank, p.apr_raw) for p, _ in offers["Кредиты"]["ranges"]] == [
            ("ВТБ", "19,900–55,400%"), ("ПСБ", "16,901–36,999%"), ("Т-Банк", "19,878–39,001%")
        ]
        assert sum(active_promo(p, region=region, now=now, hours=24) for p in promos) == 4
        after_midnight = datetime(2026, 11, 20, 0, 1, tzinfo=MOSCOW)
        assert {p.bank for p in promos if active_promo(p, region=region, now=after_midnight, hours=24)} == {
            "ПСБ", "ВТБ"
        }
        expired = rankings(products, statuses, banks, region=region,
                           now=now + timedelta(hours=73), hours=72, key_rate=14,
                           region_methods={})
        assert all(offer["checked"] == 0 for offer in expired.values())
        assert expired["Кредиты"]["ranges"] == []
        assert not any(active_promo(p, region=region, now=now + timedelta(hours=25), hours=24)
                       for p in promos)


def test_november_23_review_includes_new_lugansk_evidence():
    path = Path(__file__).resolve().parents[1] / "config" / "evidence" / "retail-2026-11-23.json"
    banks = ["Сбер", "ПСБ", "ВТБ", "Т-Банк", "РостФинанс", "ЦМР", "Генбанк"]
    now = datetime(2026, 11, 23, 23, tzinfo=MOSCOW)
    products, statuses, promos = load(path, banks, now.date())
    for region in ("lnr", "lugansk"):
        offers = rankings(products, statuses, banks, region=region, now=now, hours=72,
                          key_rate=14, region_methods={})
        assert [(p.bank, p.value) for p in offers["Вклады"]["leaders"]] == [("Т-Банк", 57500)]
        assert offers["Кредиты"]["leaders"] == []
        ranges = {p.bank: p.apr_raw for p, _ in offers["Кредиты"]["ranges"]}
        assert set(ranges) == {"ВТБ", "ПСБ", "Сбер", "Т-Банк", "ЦМР"}
        assert ranges["Сбер"] == "18,400–50,200%"
        credit_notes = {p.bank: status for p, status in offers["Кредиты"]["notes"]}
        assert set(credit_notes) == {"Генбанк", "РостФинанс"}
        assert credit_notes["Генбанк"].city_confirmed
        assert credit_notes["РостФинанс"] is None
        assert {p.bank for p, _ in offers["Вклады"]["notes"]} == {"ВТБ", "Сбер", "ПСБ", "Генбанк", "Т-Банк"}
        assert offers["Вклады на 370 дней"]["notes"] == []
        active = [p for p in promos if active_promo(p, region=region, now=now, hours=24)]
        assert len(active) == 6
        assert any(p.bank == "Генбанк" and "офисе «Луганск»" in p.text for p in active)
        assert not any("Лови момент Баланс" in p.title for p in active)


def test_november_24_promotion_review_covers_seven_banks_and_uses_entry_deadlines():
    import json
    from collections import Counter

    path = Path(__file__).resolve().parents[1] / "config" / "evidence" / "retail-2026-11-24.json"
    audit = json.loads(path.read_text(encoding="utf-8"))["promotion_review"]
    now = datetime.fromisoformat(audit["checked_at"])
    banks = {row["bank"] for row in audit["results"]}
    assert banks == {"Сбер", "ПСБ", "ВТБ", "Т-Банк", "РостФинанс", "ЦМР", "Генбанк"}
    _, _, promos = load(path, banks, now.date())
    counts = {"Сбер": 3, "ПСБ": 4, "ВТБ": 2, "Генбанк": 1}
    for region in ("lnr", "lugansk"):
        active = [p for p in promos if active_promo(p, region=region, now=now, hours=24)]
        assert Counter(p.bank for p in active) == counts
        assert all(p.regional_source for p in active)
        assert all(not p.is_guaranteed for p in active if "розыгрыш" in p.title)
    later = datetime(2026, 11, 30, 12, tzinfo=MOSCOW)
    smile = next(p for p in promos if "Улыбатл" in p.title)
    assert not active_promo(smile, region="lugansk", now=later, hours=24 * 7)
