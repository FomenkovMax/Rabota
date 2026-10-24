import ssl

import httpx
import pytest

from bankintel.domain.enums import FetchOutcome
from bankintel.sources.base import SourceRef
from bankintel.sources.discovery import discover_links
from bankintel.sources.fetcher import HttpFetcher
from bankintel.sources.storage import save_raw

SRC = SourceRef("k", "https://www.example-bank.test/page", "deposit")
UA = "TestBot/1.0"


def make(routes: dict, **kw) -> HttpFetcher:
    """routes: path -> (status, body) | Exception. Данные синтетические."""

    def handler(req: httpx.Request) -> httpx.Response:
        r = routes.get(req.url.path, (404, b""))
        if isinstance(r, Exception):
            raise r
        status, body = r
        return httpx.Response(status, content=body, headers={"content-type": "text/html"})

    return HttpFetcher(UA, min_interval_s=0, transport=httpx.MockTransport(handler), **kw)


async def test_ok_with_missing_robots():
    f = make({"/page": (200, b"<html>hello</html>")})
    doc, diag = await f.fetch(SRC)
    assert diag.outcome == FetchOutcome.OK and doc.content == b"<html>hello</html>"


async def test_robots_disallow_respected():
    f = make({"/robots.txt": (200, b"User-agent: *\nDisallow: /page"), "/page": (200, b"x")})
    doc, diag = await f.fetch(SRC)
    assert doc is None and diag.outcome == FetchOutcome.ROBOTS_DISALLOWED


@pytest.mark.parametrize("status", [401, 403, 503])
async def test_robots_unavailable_is_conservative(status):
    f = make({"/robots.txt": (status, b""), "/page": (200, b"x")})
    _, diag = await f.fetch(SRC)
    assert diag.outcome == FetchOutcome.ROBOTS_DISALLOWED


@pytest.mark.parametrize("status,body", [(403, b"forbidden"), (429, b""), (200, b"<html>Please solve the CAPTCHA</html>"),
    (200, "<script>{code:'user_blocked'}</script>Возникла проблема при открытии сайта".encode())])
async def test_blocking_is_recorded_not_bypassed(status, body):
    f = make({"/page": (status, body)})
    doc, diag = await f.fetch(SRC)
    assert doc is None and diag.outcome == FetchOutcome.BLOCKED


async def test_http_error():
    _, diag = await make({"/page": (500, b"oops")}).fetch(SRC)
    assert diag.outcome == FetchOutcome.HTTP_ERROR and diag.http_status == 500


async def test_network_error():
    _, diag = await make({"/robots.txt": httpx.ConnectError("down")}).fetch(SRC)
    assert diag.outcome == FetchOutcome.NETWORK_ERROR


async def test_tls_error_classified():
    err = httpx.ConnectError("tls")
    err.__cause__ = ssl.SSLCertVerificationError("self-signed certificate in certificate chain")
    _, diag = await make({"/robots.txt": err}).fetch(SRC)
    assert diag.outcome == FetchOutcome.TLS_ERROR


async def test_too_large():
    _, diag = await make({"/page": (200, b"x" * 100)}, max_bytes=10).fetch(SRC)
    assert diag.outcome == FetchOutcome.TOO_LARGE


def test_storage_dedup(tmp_path):
    a = save_raw(tmp_path, "b", b"data", "text/html; charset=utf-8")
    b = save_raw(tmp_path, "b", b"data", "text/html")
    assert a == b and a[1].endswith(".html") and (tmp_path / a[1]).read_bytes() == b"data"


def test_discovery_filters_foreign_and_classifies():
    html = """<a href="/deposits/main">Вклады</a>
    <a href="https://evil.test/vklad">Вклад у партнёра</a>
    <a href="https://promo.example-bank.test/x">Акции банка</a>
    <a href="/about">О банке</a><a href="/save">Накопительный счёт</a>""".encode()
    found = discover_links(html, "https://www.example-bank.test/", {"example-bank.test"})
    assert {(c.category, c.url) for c in found} == {
        ("deposit", "https://www.example-bank.test/deposits/main"),
        ("promo", "https://promo.example-bank.test/x"),
        ("savings", "https://www.example-bank.test/save"),
    }


def test_discovery_strips_utm():
    html = '<a href="/d/?utm_medium=x&id=3">Вклады</a>'.encode()
    (c,) = discover_links(html, "https://www.example-bank.test/", {"example-bank.test"})
    assert c.url == "https://www.example-bank.test/d/?id=3"


def test_ca_fingerprint_pinned():
    import hashlib, ssl
    from pathlib import Path

    pem = (Path(__file__).parents[1] / "certs" / "russian_trusted_root_ca.pem").read_text()
    digest = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest().upper()
    assert digest == "D26D2D0231B7C39F92CC738512BA541035" "19E4405D68B5BD703E9788CA8ECF31"


def test_fetcher_accepts_extra_ca(tmp_path):
    from pathlib import Path

    ca = Path(__file__).parents[1] / "certs" / "russian_trusted_root_ca.pem"
    HttpFetcher(UA, extra_ca_bundle=ca)  # не падает при загрузке PEM
