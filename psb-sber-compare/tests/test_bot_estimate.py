"""Оценка времени сбора: по прошлым сборам, без истории — по настройкам."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot import service
from src.pipeline import Config


def _config():
    return Config(raw={"browser": {"settle_ms": 5000, "pause_s": 2},
                       "banks": {"sber": {"max_pages": 80, "pause_s": 10,
                                          "block_pause_s": 600},
                                 "cmr": {}}})


def test_sber_estimate_from_settings_is_not_five_minutes(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DURATIONS", tmp_path / "t.json")
    monkeypatch.setattr(service, "_config", _config)
    text = service.collect_estimate("sber")
    # 80 страниц × (10 + 5 + 4) с ≈ 25 минут.
    assert text.startswith("около 20–30 минут (по настройкам)")
    assert "плюс 10 минут" in text


def test_estimate_follows_last_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DURATIONS", tmp_path / "t.json")
    monkeypatch.setattr(service, "_config", _config)
    for seconds in (2100, 2400, 2280):
        service.remember_duration("sber", seconds)
    assert service.collect_estimate("sber").startswith("около 30–45 минут (по прошлым сборам)")


def test_compare_without_pairs_lists_programs():
    """Кнопка «Сравнить Сбер и …» без ручных пар — сравнение по программам."""
    from types import SimpleNamespace as N

    from bot import service

    def offer(bank, value):
        return N(bank=bank, value=value, title="", url="")

    gaps = [
        N(block="MTG", program="Семейная ипотека", metric="rate_min", status="отстаёт",
          sber=offer("Сбер", 6.0), best=offer("ПСБ", 4.0),
          offers=[offer("ПСБ", 4.0), offer("Сбер", 6.0)]),
        N(block="DEP", program="Вклады", metric="rate_max", status="лидер",
          sber=offer("Сбер", 14.0), best=offer("Сбер", 14.0),
          offers=[offer("Сбер", 14.0), offer("ПСБ", 13.0)]),
        N(block="MTG", program="IT-ипотека", metric="rate_min", status="не найдено у Сбера",
          sber=None, best=offer("ПСБ", 6.0), offers=[offer("ПСБ", 6.0)]),
    ]
    text = "\n".join(service.program_lines(gaps, "ПСБ"))
    assert "🔴 проигрываем 1" in text and "🟢 выигрываем 1" in text
    assert "Семейная ипотека</b>: Сбер от 6 % · ПСБ от 4 % (+2 п.п.)" in text
    assert "Вклады</b>: Сбер до 14 % · ПСБ до 13 % (+1 п.п.)" in text
    assert text.index("Вклады") < text.index("Семейная")       # сбережения первыми
    assert "IT-ипотека</b>: Сбер — · ПСБ от 6 %" in text
