"""Парсеры получают произвольный текст с чужих сайтов: не падать неожиданно и не «зависать» на вредоносном вводе."""

import random
import time

import pytest

from bankintel.analytics.parsing import parse_money_range, parse_term
from bankintel.sources import get_adapter
from bankintel.sources.base import FetchedDocument, SourceRef
from bankintel.sources.common import ParseError, parse_rate_range
from bankintel.sources.discovery import discover_links

ALPHABET = list("0123456789 .,%-–—:;/«» ") + ["От ", "до ", "мес.", "дней", "год", "₽", "¥", "Ұ", "тыс", "млн", "ставка", "\n", "<", ">", "&"]


def rand_text(rng, n):
    return "".join(rng.choice(ALPHABET) for _ in range(rng.randint(0, n)))


def test_text_parsers_never_raise_on_random_input():
    rng = random.Random(20261024)
    for _ in range(4000):
        t = rand_text(rng, 40)
        for fn in (parse_money_range, parse_term, parse_rate_range):
            fn(t)  # результат не важен, главное — отсутствие исключений


@pytest.mark.parametrize("fn", [parse_money_range, parse_term, parse_rate_range])
@pytest.mark.parametrize("payload", ["9" * 200_000, "1 " * 100_000, "от " * 100_000, "1 000 " * 50_000, "1-" * 100_000, "%" * 200_000])
def test_parsers_are_not_vulnerable_to_catastrophic_backtracking(fn, payload):
    start = time.monotonic()
    fn(payload)
    assert time.monotonic() - start < 2.0


def test_parsed_values_keep_invariants():
    rng = random.Random(7)
    for _ in range(3000):
        t = rand_text(rng, 30)
        m = parse_money_range(t)
        if m and m.min is not None and m.max is not None:
            assert m.min >= 0 and m.max >= 0
        term = parse_term(t)
        if term:
            assert (term.values and all(v >= 0 for v in term.values)) or (term.min_days is not None and term.min_days <= term.max_days)
        r = parse_rate_range(t)
        if r and r[0] is not None and r[1] is not None:
            assert r[0] <= r[1]


@pytest.mark.parametrize("bank,key,url", [("psb", "deposits", "https://www.psbank.ru/personal/saving"), ("psb", "savings_accounts", "https://www.psbank.ru/x"),
                                          ("vtb", "deposits", "https://www.vtb.ru/personal/vklady-i-scheta/")])
def test_adapters_only_raise_parse_error_on_garbage(bank, key, url):
    rng = random.Random(1)
    adapter, src = get_adapter(bank)(bank), SourceRef(key, url, "deposit")
    docs = [b"", b"\x00\xff\xfe binary \x80", b"<html>" * 5000, ("<div class='product-card'>" * 200).encode(),
            bytes(rng.randrange(256) for _ in range(20_000)), b"<a href='/x'>" * 10_000, ("<table class='tariff-block__table'><tr><td>1</td></tr>" * 500).encode()]
    for body in docs:
        try:
            result = adapter.parse(src, FetchedDocument(url, body))
            assert isinstance(result, list)
            adapter.parse_detail(src, FetchedDocument(url, body))
        except ParseError:
            pass  # ожидаемый «страница не похожа на ожидаемую»


def test_discovery_survives_garbage_and_hostile_links():
    vk = "Вклады".encode()
    html = b"<a href='javascript:alert(1)'>" + vk + b"</a><a href='//evil.test/p'>" + vk + b"</a><a href='https://www.psbank.ru.evil.test/p'>" + vk + b"</a>" \
           b"<a href='data:text/html,x'>" + vk + b"</a><a href='/ok/page'>" + vk + b"</a>"
    found = discover_links(html, "https://www.psbank.ru/", {"psbank.ru"})
    assert [c.url for c in found] == ["https://www.psbank.ru/ok/page"]  # чужие хосты, javascript: и data: отброшены
    discover_links(bytes(random.Random(3).randrange(256) for _ in range(50_000)), "https://www.psbank.ru/", {"psbank.ru"})
