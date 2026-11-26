"""Сбор из бота идёт отдельным процессом — бот переживает его гибель."""

from __future__ import annotations

import zipfile

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


def test_snapshot_contains_only_selected_review_file(tmp_path, monkeypatch):
    data = tmp_path / "data" / "pages-all"
    data.mkdir(parents=True)
    (data / "page.txt").write_text("URL: https://example.com/", encoding="utf-8")
    evidence = tmp_path / "config" / "evidence"
    evidence.mkdir(parents=True)
    selected = evidence / "retail-current.json"
    selected.write_text('{"tariffs": [], "promotions": []}', encoding="utf-8")
    (evidence / "retail-previous.json").write_text("{}", encoding="utf-8")
    (evidence.parent / "settings.yaml").write_text("private config", encoding="utf-8")
    monkeypatch.setattr(service, "ROOT", tmp_path)
    monkeypatch.setattr(service, "_config", lambda: service.Config({"reviewed_offers": str(selected)}))

    with zipfile.ZipFile(service.full_snapshot_archive()) as snapshot:
        assert set(snapshot.namelist()) == {"pages-all/page.txt", "config/evidence/retail-current.json"}
        assert snapshot.read("config/evidence/retail-current.json") == selected.read_bytes()
