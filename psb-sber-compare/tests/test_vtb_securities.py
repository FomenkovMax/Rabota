from src import availability, securities
from src.banks.vtb_securities import tariff_bonds


def test_subordinated_tariff_sections_link_corrected_instrument(tmp_path):
    file = tmp_path / "tariffs.html"
    file.write_text("""
        <h2>Список субординированных облигаций ВТБ с комиссией 0%</h2>
        <div>СУБ-Т1-8</div><div>ISIN: RU000A103S8</div>
        <div>СУБ-Т2-1</div><div>ISIN: RU000A102&nbsp;879</div>
        <h2>Другой раздел</h2>
        <div>СУБ-Т1-4</div><div>ISIN: RU000A102QN9</div>
        """, encoding="utf-8")
    corrected, original = tariff_bonds(file)
    assert corrected.terms[securities.ISIN] == "RU000A103S89"
    assert corrected.terms["Источник проверки ISIN"].startswith("https://www.moex.com/")
    assert original.terms[securities.ISIN] == "RU000A102879"
    assert not availability.status_of(corrected, region_method="federal").city_confirmed
