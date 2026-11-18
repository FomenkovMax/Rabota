"""Read the public T-Bank securities catalogues to audit issue coverage."""

from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from urllib.parse import parse_qs, urlsplit

from .browser import PageFailed, PageReader, PageTooSlow
from .crawl_adapter import is_blocked, is_not_found
from .others import TbankAdapter
from ..pipeline import Config
from ..securities import issue_kind


def _offset(url: str) -> int:
    return int(parse_qs(urlsplit(url).query).get("start", ["0"])[0])


def collect_catalogue(reader: PageReader, adapter: TbankAdapter, root: str,
                      output: Path) -> dict:
    """Visit the bank's own pagination links and save an inventory as they are read."""
    pages: dict[str, list[str]] = {}
    failures: dict[str, str] = {}
    pending = {root}
    page_size = adapter.catalogue_pages[urlsplit(root).path.rstrip("/")][0]
    started = datetime.now().isoformat(timespec="seconds")
    while pending:
        url = min(pending, key=_offset)
        pending.remove(url)
        error = ""
        for _ in range(2):
            try:
                data = reader.read(url)
                links = adapter._links(data.get("links") or [])
                issues = [item for item in links if item.startswith(root) and issue_kind(item)]
                if issues and not is_blocked(data) and not is_not_found(data):
                    pages[url] = issues
                    pending.update(item for item in links if item.startswith(root + "?")
                                   and item not in pages and item not in failures)
                    break
                error = "Сайт не показал строки каталога"
            except (PageFailed, PageTooSlow) as exc:
                error = str(exc)
        else:
            failures[url] = error

        last_offset = max(map(_offset, pending | pages.keys() | failures.keys()))
        missing_offsets = sorted(set(range(0, last_offset + 1, page_size))
                                 - {_offset(page) for page in pages})
        state = {
            "source": root,
            "started_at": started,
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "pages": pages,
            "pending": sorted(pending),
            "failures": failures,
            "expected_pages": 1 + last_offset // page_size,
            "missing_offsets": missing_offsets,
            "unique_issues": len({issue for group in pages.values() for issue in group}),
        }
        temporary = output.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(output)
        print(root, "страниц", len(pages), "в очереди", len(pending),
              "ошибок", len(failures), flush=True)
    return state


def audit_inventory(directory: Path, database: Path, adapter: TbankAdapter) -> dict:
    """Compare issue URLs with the latest successful snapshot without writing to SQLite."""
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        run_id = db.execute("SELECT max(id) FROM runs WHERE status='ok'").fetchone()[0]
        if run_id is None:
            raise ValueError("В базе нет завершённого сбора")
        rows = db.execute(
            "SELECT source_url FROM products WHERE run_id=? AND bank=? AND category=?",
            (run_id, adapter.title, "Инвестиции"),
        )
        collected = {adapter._normalize(url) for (url,) in rows if url and issue_kind(url)}

    audit: dict = {"run_id": run_id, "catalogues": {}}
    for kind in ("stocks", "bonds"):
        path = directory / (kind + ".json")
        if not path.is_file():
            audit["catalogues"][kind] = {"unread": True}
            continue
        state = json.loads(path.read_text(encoding="utf-8"))
        issue_urls = [adapter._normalize(url) for page in state["pages"].values() for url in page]
        catalogue = set(issue_urls)
        audit["catalogues"][kind] = {
            "pages_read": len(state["pages"]),
            "expected_pages": state["expected_pages"],
            "missing_offsets": state["missing_offsets"],
            "page_failures": state["failures"],
            "repeat_rows": len(issue_urls) - len(catalogue),
            "catalogue_issues": len(catalogue),
            "in_snapshot": len(catalogue & collected),
            "missing_issue_urls": sorted(catalogue - collected),
        }
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--database", type=Path, help="compare a saved inventory against this database")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    config = Config.load().bank_settings("tbank")
    adapter = TbankAdapter(region=None, settings=config)
    if args.database:
        audit = audit_inventory(args.output, args.database, adapter)
        (args.output / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2),
                                              encoding="utf-8")
        return
    settings = adapter.browser_settings()
    settings.expand = False
    with PageReader(settings) as reader:
        for path in adapter.catalogue_pages:
            root = adapter.base_url + path + "/"
            collect_catalogue(reader, adapter, root, args.output / (path.rsplit("/", 1)[1] + ".json"))


if __name__ == "__main__":
    main()
