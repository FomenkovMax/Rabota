import pytest

from lnrbank.calc import formulas as f
from lnrbank.calc.scenarios import compute_scenario
from lnrbank.config import load_settings

SC = load_settings().scenarios


def test_annuity_reference_value():
    # Эталон: 300 000 ₽, 20 % годовых, 36 мес → 11 149,07 ₽ (расчёт по формуле аннуитета).
    assert f.annuity_payment(300_000, 20, 36) == pytest.approx(11_149.07, abs=1)


def test_annuity_schedule_repays_principal():
    pay, balance, r = f.annuity_payment(1_000_000, 18.5, 60), 1_000_000.0, 18.5 / 1200
    for _ in range(60):
        balance = balance * (1 + r) - pay
    assert abs(balance) < 1


def test_annuity_zero_rate():
    assert f.annuity_payment(120_000, 0, 12) == pytest.approx(10_000)


def test_deposit_income():
    assert f.deposit_income(1_000_000, 14, 12, capitalization=False) == pytest.approx(140_000)
    # Ежемесячная капитализация: 1 000 000 × ((1 + 0,14/12)^12 − 1) ≈ 149 342 ₽.
    assert f.deposit_income(1_000_000, 14, 12, capitalization=True) == pytest.approx(149_342, abs=1)


def test_effective_rate():
    assert f.effective_rate(14) == pytest.approx(14.934, abs=0.001)


def test_debit_card_cashback_capped_by_limit():
    # 30 000 × 5 % = 1 500 > лимит 1 000 → 12 000 в год; остаток 50 000 × 10 % = 5 000; минус 1 200.
    got = f.debit_card_annual_benefit(30_000, 5, 1_000, 50_000, 10, 100)
    assert got == pytest.approx(12_000 + 5_000 - 1_200)


def test_credit_card_cash_fee_minimum():
    assert f.credit_card_annual_cost(0, 10_000, 3.9, 390) == pytest.approx(390)
    assert f.credit_card_annual_cost(99, 10_000, 3.9, 290) == pytest.approx(99 * 12 + 390)


def test_scenario_missing_inputs_gives_na_without_substitution():
    res = compute_scenario("DEP-2", SC["DEP-2"], {"rate_12m_online": 14.0})
    assert res.status == "н/д" and "capitalization" in res.missing
    assert res.metrics == {}


def test_deposit_scenario():
    res = compute_scenario("DEP-2", SC["DEP-2"], {"rate_12m_online": 14.0, "capitalization": False})
    assert res.metrics["income"] == pytest.approx(140_000)
    assert res.calc_method == "agent_formula"


def test_mortgage_down_payment_below_minimum_is_na():
    params = {"rate_new_regions": 2.0, "down_payment_min_pct": 30, "loan_max": 6_000_000}
    res = compute_scenario("MTG-1", SC["MTG-1"], params)
    assert res.status == "н/д" and "ПВ" in res.reason


def test_mortgage_per_program():
    params = {
        "rate_new_regions": 2.0,
        "rate_market_primary": 24.0,
        "down_payment_min_pct": 10,
        "loan_max": 6_000_000,
    }
    res = compute_scenario("MTG-1", SC["MTG-1"], params)
    assert set(res.by_program) == {"new_regions", "market_primary"}
    assert res.by_program["new_regions"]["payment"] < res.by_program["market_primary"]["payment"]
