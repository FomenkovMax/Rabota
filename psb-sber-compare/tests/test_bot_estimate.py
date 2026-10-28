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
