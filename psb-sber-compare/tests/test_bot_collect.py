"""Сбор из бота идёт отдельным процессом — бот переживает его гибель."""

from __future__ import annotations

import pytest

service = pytest.importorskip("bot.service")


def test_collect_command():
    assert service.collect_command("all")[-1] == "collect"
    assert service.collect_command("sber")[-2:] == ["--bank", "sber"]


def test_killed_collection_is_reported_not_silent():
    text = service.collect_summary("all", -9, [])
    assert "прервался" in text and "памяти" in text


def test_failed_collection_shows_last_lines():
    text = service.collect_summary("sber", 1, ["шаг 1", "Ошибка <b>"])
    assert "код 1" in text and "Ошибка &lt;b&gt;" in text
