"""Read the public T-Bank securities catalogues to audit issue coverage."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .browser import BrowserSettings, PageFailed, PageReader, PageTooSlow
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    config = Config.load().bank_settings("tbank")
    adapter = TbankAdapter(region=None, settings=config)
    settings = BrowserSettings.from_config(config.get("browser"))
    settings.expand = False
    settings.pause_s = float(config.get("pause_s") or settings.pause_s)
    with PageReader(settings) as reader:
        for path in adapter.catalogue_pages:
            root = adapter.base_url + path + "/"
            collect_catalogue(reader, adapter, root, args.output / (path.rsplit("/", 1)[1] + ".json"))


if __name__ == "__main__":
    main()
