"""Keep crawler evidence from tests away from working snapshots."""
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_crawl_artifacts(monkeypatch, tmp_path):
    from src.banks.crawl_adapter import CrawlAdapter

    def pages(self):
        return Path(self.settings["pages_dir"]) if self.settings.get("pages_dir") else tmp_path / "pages" / self.code

    def missing(self):
        return tmp_path / "missing" / self.code

    monkeypatch.setattr(CrawlAdapter, "_pages_dir", pages)
    monkeypatch.setattr(CrawlAdapter, "_missing_dir", missing)
