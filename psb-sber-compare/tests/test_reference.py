"""Эталон продуктов: всё ли нашёл сбор."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import pipeline, reference


def _p(title, path, bank="Сбер"):
    return SimpleNamespace(bank=bank, title=title, source_url="https://www.sberbank.ru" + path)


def test_reference_found_by_path_or_pattern():
    ref = {"bank": "Сбер", "products": [
        {"name": "Вклад Лучший %", "path": "/ru/person/contributions/deposits/vklad/vklad_luchshiy_procent"},
        {"name": "СберВклад", "match": "^сбервклад$"},
        {"name": "СберПервый", "match": "^сберпервый$"},
        {"name": "Старый вклад", "path": "/x", "active": False},
    ]}
    got = reference.check(ref, [
        _p("Вклад Лучший %", "/ru/person/contributions/deposits/vklad/vklad_luchshiy_procent/"),
        _p("СберВклад", "/ru/person/contributions/deposits/sbervklad_a"),
        _p("Карта СберПервый × Аэрофлот", "/ru/person/bank_cards/debit/premium_aeroflot"),
        _p("СберПервый", "/x", bank="ВТБ"),
    ])
    assert got.share == "2 из 3"
    assert [m["name"] for m in got.missing] == ["СберПервый"]


def test_sber_reference_file_is_valid():
    ref = reference.load("sber")
    assert ref["bank"] == "Сбер" and len(ref["products"]) > 100
    assert all(p.get("path") or p.get("match") for p in ref["products"])


def test_new_candidates_after_baseline(tmp_path):
    path = tmp_path / "seen.json"
    crawl = {"Сбер": {"candidates": ["https://s/ru/a"]}}
    pipeline.mark_new_candidates(crawl, path=path, today="2026-11-03")
    assert crawl["Сбер"]["new_candidates"] == []          # первый раз — точка отсчёта
    crawl = {"Сбер": {"candidates": ["https://s/ru/a", "https://s/ru/sberblizhe"]}}
    pipeline.mark_new_candidates(crawl, path=path, today="2026-11-10")
    assert crawl["Сбер"]["new_candidates"] == ["https://s/ru/sberblizhe"]
    pipeline.mark_new_candidates(crawl, path=path, today="2026-11-30")
    assert crawl["Сбер"]["new_candidates"] == []          # через неделю — уже не новое
