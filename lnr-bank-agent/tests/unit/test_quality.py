from lnrbank.quality.rules import coverage, is_comparable, product_issues, row_issues


def row(**kw):
    base = dict(
        bank="SBER",
        product_id="SBER-LOAN-x",
        parameter="rate_min",
        value="20",
        region_method="selector",
        confidence="high",
        source_url="https://s",
        collected_at="2026-10-05T10:00",
        evidence="от 20 %",
    )
    return {**base, **kw}


def test_missing_evidence_is_issue():
    assert "missing:evidence" in row_issues(row(evidence=""), block="LOAN", key_rate=14)


def test_psk_below_rate_is_issue():
    rows = [row(parameter="rate_min", value="20"), row(parameter="psk_min", value="18")]
    assert any(i.startswith("psk_below_rate") for i in product_issues(rows))


def test_deposit_far_above_key_rate_flagged():
    r = row(parameter="rate_12m_online", value="18", product_id="SBER-DEP-x")
    assert "recheck:deposit_above_key" in row_issues(r, block="DEP", key_rate=14)


def test_loan_below_key_rate_flagged_but_not_gov_mortgage():
    loan = row(parameter="rate_min", value="9.9")
    assert "recheck:loan_below_key" in row_issues(loan, block="LOAN", key_rate=14)
    gov = row(parameter="rate_new_regions", value="2", product_id="SBER-MTG-x")
    assert row_issues(gov, block="MTG", key_rate=14) == []


def test_is_comparable():
    assert is_comparable(row())
    assert not is_comparable(row(region_method="not_confirmed"))
    assert not is_comparable(row(confidence="low"))
    assert not is_comparable(row(value="н/д"))


def test_coverage():
    rows = [row(parameter="rate_min"), row(parameter="psk_min", value="н/д")]
    assert coverage(["rate_min", "psk_min", "amount_max", "term_max_months"], rows) == 25.0
