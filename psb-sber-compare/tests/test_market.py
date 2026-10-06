"""Место Сбера, проверки правдоподобия, product_id, ключевая ставка, BI."""

from __future__ import annotations

import csv
from datetime import date

from src import keyrate, market
from src.changes import detect_changes
from src.psb.parser import Product


def P(bank, title, category, rate_min=None, rate_max=None, **kw) -> Product:
    if rate_max is None:
        rate_max = rate_min
    return Product(bank=bank, title=title, category=category,
                   rate_min=rate_min, rate_max=rate_max, **kw)


KEY = 14.0


# --- проверки правдоподобия -----------------------------------------------

def check(product, method="selector"):
    return market.assess(product, key_rate=KEY, region_method=method)


def test_deposit_far_above_key_rate_is_low():
    result = check(P("ПСБ", "Вклад «Александр Невский»", "Вклады", 21.0, 31.0))
    assert result.confidence == market.LOW and not result.usable
    assert "выше ключевой" in result.issues[0]
    # 17 % при ключевой 14 % — ровно на границе, это ещё нормально.
    assert check(P("ПСБ", "Вклад", "Вклады", 10.0, 17.0)).confidence == market.HIGH


def test_cheap_loan_needs_state_programme():
    assert check(P("ПСБ", "Ипотека от ПСБ и ГК Самолет", "Ипотека", 10.0)).confidence == market.LOW
    assert check(P("ПСБ", "Госпрограмма. Новые субъекты 2%", "Ипотека", 2.0)).usable
    assert check(P("Сбер", "Семейная ипотека", "Ипотека", 6.0)).usable


def test_psk_below_rate_is_parse_error_except_credit_cards():
    loan = P("ПСБ", "Кредит под залог автомобиля", "Кредиты", 29.9, apr_min=27.4)
    assert check(loan).confidence == market.LOW
    # Сотые доли — разные сценарии у «ставка от» и «ПСК от», не ошибка.
    assert check(P("ПСБ", "Автокредит", "Кредиты", 18.75, apr_min=18.7)).usable
    # У кредитки ПСК законно ниже ставки из-за льготного периода.
    assert check(P("ПСБ", "Кредитная карта", "Кредитные карты", 59.99, apr_min=40.0)).usable


def test_cashback_percent_is_not_checked_as_rate():
    card = P("ПСБ", "Дебетовая карта «Твой кешбэк»", "Дебетовые карты", 10.0)
    result = check(card)
    assert result.confidence == market.HIGH and not result.has_rate


def test_section_page_showcase_and_region():
    assert check(P("ПСБ", "Вклады с высоким процентом для физических лиц",
                   "Вклады", 10.0)).confidence == market.LOW
    showcase = P("Сбер", "Вклад «Лучший %»", "Вклады", 13.5,
                 terms={"Источник ставки": "витрина"})
    assert check(showcase).confidence == market.MEDIUM and check(showcase).usable
    assert check(P("ВТБ", "Вклад", "Вклады", 13.0), "not_confirmed").confidence == market.LOW


def test_no_key_rate_skips_key_rate_checks_only():
    deposit = P("ПСБ", "Вклад", "Вклады", 31.0)
    assert market.assess(deposit, key_rate=None, region_method="selector").usable


# --- программы и product_id -----------------------------------------------

def test_programmes():
    def prog(title, category):
        return market.program_of(P("ПСБ", title, category))

    assert prog("Кредит без залога", "Кредиты") == "Потребительский кредит"
    assert prog("Кредит под залог автомобиля", "Кредиты") == "Кредит под залог"
    assert prog("Автокредит", "Кредиты") == "Автокредит"
    assert prog("Семейная военная ипотека", "Ипотека") == "Военная ипотека"
    assert prog("Военная ипотека. Рефинансирование", "Ипотека") == "Военная ипотека"
    assert prog("Госпрограмма. Новые субъекты 2%", "Ипотека") == "Льготная для новых регионов"
    assert prog("Ипотека на новостройку", "Ипотека") == "Новостройки"
    assert prog("Ипотека", "Ипотека") == "Рыночная ипотека"


def test_product_id_from_address_survives_rename():
    a = P("Сбер", "Вклад «Лучший %»", "Вклады", 13.5,
          url_path="/ru/person/contributions/deposits/vklad_luchshiy")
    b = P("Сбер", "Вклад «Лучший процент»", "Вклады", 14.0,
          url_path="/ru/person/contributions/deposits/vklad_luchshiy")
    assert market.product_ids([a])[id(a)] == "SBER-DEP-vklad-luchshiy"
    assert market.product_ids([b])[id(b)] == "SBER-DEP-vklad-luchshiy"


def test_product_id_collision_and_shared_page():
    debit = P("Сбер", "СберКарта", "Дебетовые карты", url_path="/cards/debit/sberkarta")
    credit = P("Сбер", "Кредитная СберКарта", "Кредитные карты",
               url_path="/cards/credit/sberkarta")
    shared1 = P("ЦМР", "Вклад «Классика»", "Вклады", 12.0,
                url_path="https://cmr.ru/deposits#вклад «классика»")
    shared2 = P("ЦМР", "Вклад «Доход»", "Вклады", 13.0,
                url_path="https://cmr.ru/deposits#вклад «доход»")
    ids = market.product_ids([debit, credit, shared1, shared2])
    assert ids[id(debit)] == "SBER-CARD-debit-sberkarta"
    assert ids[id(credit)] == "SBER-CARD-credit-sberkarta"
    assert ids[id(shared1)] == "CMR-DEP-vklad-klassika"
    assert ids[id(shared2)] == "CMR-DEP-vklad-dokhod"
    assert len(set(ids.values())) == 4


# --- место Сбера ------------------------------------------------------------

def gaps(products, methods=None):
    found = market.build_gaps(products, home="Сбер", key_rate=KEY,
                              region_methods=methods or {}, parity_pp=0.5)
    return {g.program: g for g in found}


def test_place_best_median_and_status():
    result = gaps([
        P("Сбер", "Вклад «Лучший %»", "Вклады", 10.0, 14.0),
        P("Сбер", "Вклад «Простой»", "Вклады", 10.0, 12.0),
        P("ПСБ", "Вклад «Мой доход»", "Вклады", 11.0, 15.0),
        P("ВТБ", "Вклад", "Вклады", 13.8),
        P("ЦМР", "Вклад", "Вклады", 13.0),
        P("ПСБ", "Вклад «Невский»", "Вклады", 21.0, 31.0),     # не прошёл проверку
    ])
    deposit = result["Вклады"]
    assert deposit.sber.value == 14.0                          # лучший вклад Сбера
    assert deposit.best.bank == "ПСБ" and deposit.best.value == 15.0
    assert deposit.others_median == 13.8
    assert deposit.place == "2 из 4"
    assert deposit.status == market.IN_MARKET                  # лучше медианы
    assert deposit.delta_vs_best == -1.0


def test_loans_lower_is_better_and_behind():
    result = gaps([
        P("Сбер", "Кредит наличными", "Кредиты", 19.9),
        P("ПСБ", "Кредит наличными", "Кредиты", 16.9),
        P("ВТБ", "Кредит наличными", "Кредиты", 17.5),
    ])
    loan = result["Потребительский кредит"]
    assert loan.status == market.BEHIND and loan.place == "3 из 3"
    assert loan.advantage == -2.7


def test_leader_absent_and_unconfirmed_region():
    result = gaps([
        P("Сбер", "Семейная ипотека", "Ипотека", 5.5),
        P("ПСБ", "Семейная ипотека", "Ипотека", 6.0),
        P("ВТБ", "Семейная ипотека", "Ипотека", 4.0),          # регион не ЛНР
        P("ПСБ", "Военная ипотека", "Ипотека", 16.8),
    ], methods={"ВТБ": "not_confirmed"})
    assert result["Семейная ипотека"].status == market.LEADER
    assert result["Семейная ипотека"].banks_compared == 2
    assert result["Военная ипотека"].status == market.NO_SBER


def test_quality_coverage_and_manual_list():
    rows, manual = market.quality([
        P("ПСБ", "Вклад «Невский»", "Вклады", 31.0),
        P("ПСБ", "Вклад «Мой доход»", "Вклады", 13.8),
        P("ПСБ", "Вклад «Без ставки»", "Вклады"),
        P("ПСБ", "Дебетовая карта", "Дебетовые карты", 7.0),
    ], key_rate=KEY, region_methods={})
    dep = next(r for r in rows if r.block == "DEP")
    card = next(r for r in rows if r.block == "CARD")
    assert (dep.products, dep.rated, dep.usable) == (3, 3, 1)
    assert dep.coverage_pct == 33.3
    assert card.coverage_pct is None                            # ставок у блока нет
    assert [p.title for p, _ in manual] == ["Вклад «Невский»"]  # без ставки — не сюда


# --- ключевая ставка ---------------------------------------------------------

PAGE = """<table><tr><td>06.10.2026</td><td>14,00</td></tr>
<tr><td>12.09.2026</td><td>14,00</td></tr><tr><td>11.09.2026</td><td>14,25</td></tr></table>"""


def test_key_rate_parse():
    assert keyrate.parse(PAGE).value == 14.0
    assert keyrate.parse(PAGE).label == "14,00 % на 06.10.2026"
    older = keyrate.parse(PAGE, on_or_before=date(2026, 9, 11))
    assert (older.value, older.on) == (14.25, "2026-09-11")
    assert keyrate.parse("<html></html>") is None


def test_key_rate_from_settings_only_for_same_day(tmp_path, monkeypatch):
    from src.storage import Storage

    monkeypatch.setattr(keyrate, "on_date", lambda day: None)   # ЦБ недоступен
    storage = Storage(tmp_path / "db.sqlite")
    run = storage.start_run("ЛНР")
    settings = {"value": 15.0, "date": "2026-10-06"}
    assert keyrate.ensure(storage, run, "2025-01-10T09:00", settings) is None
    rate = keyrate.ensure(storage, run, "2026-10-06T09:00", settings)
    assert rate.value == 15.0 and storage.key_rate_of(run) == (15.0, "2026-10-06")


# --- изменения и BI ---------------------------------------------------------

def _two_runs(tmp_path):
    from src.storage import Storage

    storage = Storage(tmp_path / "db.sqlite")
    first = storage.start_run("ЛНР")
    storage.save_products(first, [
        P("ВТБ", "Вклад «Надёжный»", "Вклады", 10.0, 18.0, url_path="/vtb/nadezhny"),
        P("Сбер", "Кредит наличными", "Кредиты", 19.9, url_path="/sber/cash"),
    ])
    storage.finish_run(first, psb=2, sber=0, promos=0)
    storage.conn.execute("UPDATE runs SET started_at='2026-09-29T09:00', key_rate=14,"
                         " key_rate_date='2026-09-29' WHERE id=?", (first,))
    second = storage.start_run("ЛНР")
    storage.save_products(second, [
        P("ВТБ", "Вклад «Надёжный»", "Вклады", 10.0, 16.0, url_path="/vtb/nadezhny"),
        P("Сбер", "Кредит наличными", "Кредиты", 19.9, url_path="/sber/cash"),
    ])
    storage.save_changes(second, detect_changes(storage, second, first))
    storage.finish_run(second, psb=2, sber=0, promos=0)
    storage.conn.execute("UPDATE runs SET started_at='2026-10-06T09:00', key_rate=14,"
                         " key_rate_date='2026-10-06' WHERE id=?", (second,))
    storage.conn.commit()
    return storage, second


def test_changes_cover_every_bank_and_upper_bound(tmp_path):
    storage, second = _two_runs(tmp_path)
    changes = [dict(r) for r in storage.changes_of_run(second)]
    assert len(changes) == 1
    assert changes[0]["bank"] == "ВТБ" and changes[0]["field"] == "Ставка до"
    assert changes[0]["delta"] == -2.0 and changes[0]["severity"] == "high"


def test_bi_tables_link_by_product_id(tmp_path):
    from src.export import bi

    storage, _ = _two_runs(tmp_path)
    tables = bi.collect_tables(storage, home="Сбер", region_methods={})
    assert [r["snapshot_date"] for r in tables["snapshots"]] == ["2026-09-29", "2026-10-06"]
    ids = {r["product_id"] for r in tables["products"]}
    assert ids == {"VTB-DEP-nadezhny", "SBER-LOAN-cash"}
    assert {r["product_id"] for r in tables["conditions"]} <= ids
    change = tables["changes"][0]
    assert change["product_id"] == "VTB-DEP-nadezhny" and change["alert"] == "yes"
    assert change["prev_snapshot_date"] == "2026-09-29"
    rate = next(r for r in tables["conditions"]
                if r["parameter"] == "rate_max" and r["product_id"] == "VTB-DEP-nadezhny"
                and r["snapshot_date"] == "2026-10-06")
    assert (rate["value"], rate["better"], rate["unit"]) == ("16", "higher", "% годовых")

    paths = bi.write(tmp_path / "bi", tables)
    with (tmp_path / "bi" / "gaps.csv").open(encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert rows and rows[0]["snapshot_date"] == "2026-09-29"
    assert any(p.name == "data_dictionary.md" for p in paths)


def test_new_local_setting_applies_to_old_unconfirmed_data():
    old = P("ЦМР", "Вклад «ЦМР Старт»", "Вклады", 15.0)
    old.region_method = "not_confirmed"
    assert market.method_of(old, {"ЦМР": "local"}) == "local"
    chosen = P("Сбер", "Вклад", "Вклады", 14.0)
    chosen.region_method = "selector"
    assert market.method_of(chosen, {"Сбер": "not_confirmed"}) == "selector"
