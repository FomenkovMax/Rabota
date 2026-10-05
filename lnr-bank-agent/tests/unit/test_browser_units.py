from pathlib import Path

from lnrbank.browser.antibot import detect_block
from lnrbank.browser.robots import RobotsGate
from lnrbank.net.cbr import parse_key_rate

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def test_sber_js_challenge_detected():
    html = (FIX / "region" / "sber_antibot.html").read_text(encoding="utf-8")
    assert detect_block(html, text="") is not None


def test_captcha_detected_and_normal_page_passes():
    assert detect_block("<div>Подтвердите, что вы не робот</div>", "Подтвердите, что вы не робот")
    page = "<html><body><h1>Вклады</h1><p>Ставка 14 %</p></body></html>"
    assert detect_block(page, "Вклады Ставка 14 %") is None


def test_robots_disallow():
    gate = RobotsGate(fetch=lambda url: "User-agent: *\nDisallow: /private/\n")
    assert not gate.allowed("https://bank.ru/private/a")
    assert gate.allowed("https://bank.ru/personal/deposits")


def test_robots_unavailable_allows():
    def boom(url):
        raise OSError("404")

    assert RobotsGate(fetch=boom).allowed("https://bank.ru/x")


def test_key_rate_parsed():
    html = (FIX / "cbr" / "keyrate.html").read_text(encoding="utf-8")
    assert parse_key_rate(html) == ("2026-10-05", 14.0)


def test_playbook_entries_valid():
    from lnrbank.check import load_playbook
    from lnrbank.config import load_settings

    methods = {"selector", "calc_checkbox", "regional_tariff", "federal_confirmed"}
    playbook = load_playbook()
    for bank in load_settings().banks:
        home = playbook[bank]["home"]
        assert home["url"].startswith("https://")
        assert home["region_method"] in methods
        assert home["verify"]["any_text"]
        assert home["steps"] == "auto" or isinstance(home["steps"], list)
