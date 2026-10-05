import os
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from lnrbank.browser.region import bind_region

FIX = (Path(__file__).resolve().parents[1] / "fixtures" / "region").as_uri()
EXE = os.environ.get("LNRBANK_CHROMIUM") or None
LUGANSK = {"any_text": ["Луганск"], "within": "header"}


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE)
        yield b
        b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context()
    yield ctx.new_page()
    ctx.close()


def test_selector_binding(page):
    spec = {
        "url": f"{FIX}/selector.html",
        "region_method": "selector",
        "verify": LUGANSK,
        "steps": [
            {"action": "click", "selector": "#city"},
            {"action": "click_text", "text": "Луганск", "within": "#list"},
        ],
    }
    b = bind_region(page, spec)
    assert b.ok and b.method == "selector" and "Луганск" in b.evidence


def test_auto_strategy_without_steps(page):
    spec = {
        "url": f"{FIX}/selector.html",
        "region_method": "selector",
        "verify": LUGANSK,
        "steps": "auto",
    }
    assert bind_region(page, spec, city="Луганск").ok


def test_checkbox_binding(page):
    spec = {
        "url": f"{FIX}/checkbox.html",
        "region_method": "calc_checkbox",
        "verify": {"any_text": ["новых регионов"], "within": "#programs"},
        "steps": [{"action": "check", "selector": "#nr"}],
    }
    b = bind_region(page, spec)
    assert b.ok and b.method == "calc_checkbox"


def test_reset_region_rebound(page):
    spec = {
        "url": f"{FIX}/reset.html",
        "region_method": "selector",
        "verify": LUGANSK,
        "steps": [
            {"action": "click", "selector": "#city"},
            {"action": "click_text", "text": "Луганск", "within": "#list"},
        ],
    }
    assert bind_region(page, spec).ok
    page.goto(f"{FIX}/reset.html")  # переход сбрасывает регион
    again = bind_region(page, spec, navigate=False)
    assert again.ok and again.rebound


def test_failed_binding_is_not_confirmed(page):
    spec = {
        "url": f"{FIX}/checkbox.html",
        "region_method": "selector",
        "verify": LUGANSK,
        "steps": [{"action": "click", "selector": "#missing"}],
    }
    b = bind_region(page, spec, timeout_ms=1500)
    assert not b.ok and b.method == "not_confirmed" and b.reason
