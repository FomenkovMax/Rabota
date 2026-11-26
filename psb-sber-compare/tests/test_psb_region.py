from src.banks.psb import selected_city


def test_city_is_read_from_selected_header_not_footer_or_directory():
    assert selected_city('<footer>Луганская Народная Республика</footer>') == ""
    assert selected_city('<select><option>Луганск</option></select>') == ""
    assert selected_city('<span class="header-location__text">Луганск</span>') == "Луганск"
    assert selected_city('<span class="header-location__text">Москва</span><p>Луганск</p>') == "Москва"
