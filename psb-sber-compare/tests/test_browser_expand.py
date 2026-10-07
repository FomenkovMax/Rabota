"""Раскрытие вкладок с условиями в настоящем браузере (если он установлен)."""

import functools
import http.server
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

pytest.importorskip("playwright")

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Кредит</title></head><body>
<h1>Кредит наличными</h1>
<nav><a href="/other.html">Условия</a> <button id="t">Подробные условия</button></nav>
<div id="d" style="display:none"><div>Ставка</div><div>От 20,4%</div></div>
<script>document.getElementById('t').onclick=()=>{document.getElementById('d').style.display='block'};</script>
</body></html>"""


@pytest.fixture()
def site(tmp_path):
    (tmp_path / "index.html").write_text(PAGE, encoding="utf-8")
    (tmp_path / "other.html").write_text("<html><body>OTHER</body></html>", encoding="utf-8")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/index.html"
    server.shutdown()


def test_details_tab_is_opened_without_leaving_page(site, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    from src.banks.browser import BrowserSettings, browser_session

    try:
        with browser_session(BrowserSettings(settle_ms=300, pause_s=0)) as session:
            data = session.inspect(site)
    except Exception as exc:                        # noqa: BLE001
        pytest.skip(f"браузер недоступен: {exc}")
    assert "От 20,4%" in data["text"]
    assert data["url"].endswith("/index.html")
