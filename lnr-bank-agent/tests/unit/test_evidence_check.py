from lnrbank.extract.clean import evidence_in_source, html_to_text, normalize


def test_nbsp_and_spaces_normalized():
    src = "Ставка 14,2 % на\n12   месяцев"
    assert evidence_in_source("Ставка 14,2 % на 12 месяцев", src)


def test_missing_quote_rejected():
    assert not evidence_in_source("Ставка 15 %", "Ставка 14,2 % на 12 месяцев")


def test_empty_quote_rejected():
    assert not evidence_in_source("", "что угодно")


def test_html_to_text_drops_scripts_keeps_tables():
    html = (
        "<html><script>var x='Ставка 99 %'</script><p>Вклад</p><table>"
        "<tr><th>Срок</th><th>Ставка</th></tr><tr><td>12 мес</td><td>14,2 %</td></tr>"
        "</table></html>"
    )
    text = html_to_text(html)
    assert "99 %" not in text
    assert "| 12 мес | 14,2 % |" in text


def test_normalize_collapses_whitespace():
    assert normalize("a  \t b\n\nc") == "a b c"


def test_numeric_values_normalized():
    from lnrbank.config import Parameter
    from lnrbank.extract.schema import normalize_value

    pct = Parameter(unit="% годовых", better="higher", description="")
    rub = Parameter(unit="₽", better="lower", description="")
    assert normalize_value("14,20 %", pct) == "14.2"
    assert normalize_value("1 000 000 ₽", rub) == "1000000"
    assert normalize_value("10000000000000000", rub) == "10000000000000000"
    for bad in ("inf", "nan", "много"):
        assert normalize_value(bad, rub) is None
    assert normalize_value("н/д", rub) == "н/д"
