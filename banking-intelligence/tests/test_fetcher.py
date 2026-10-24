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


@pytest.mark.parametrize("status,outcome", [
    (401, FetchOutcome.ROBOTS_DISALLOWED), (503, FetchOutcome.ROBOTS_DISALLOWED), (403, FetchOutcome.BLOCKED)])
async def test_robots_unavailable_is_conservative(status, outcome):
    f = make({"/robots.txt": (status, b""), "/page": (200, b"x")})
    doc, diag = await f.fetch(SRC)
    assert doc is None and diag.outcome == outcome


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
    import hashlib
    import ssl
    from pathlib import Path

    pem = (Path(__file__).parents[1] / "certs" / "russian_trusted_root_ca.pem").read_text()
    digest = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest().upper()
    assert digest == "D26D2D0231B7C39F92CC738512BA541035" "19E4405D68B5BD703E9788CA8ECF31"


def test_fetcher_accepts_extra_ca(tmp_path):
    from pathlib import Path

    ca = Path(__file__).parents[1] / "certs" / "russian_trusted_root_ca.pem"
    HttpFetcher(UA, extra_ca_bundle=ca)  # не падает при загрузке PEM


async def test_network_error_retried_once():
    calls = {"n": 0}

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectTimeout("")
        return httpx.Response(200, content=b"ok", headers={"content-type": "text/html"})

    f = HttpFetcher(UA, min_interval_s=0, transport=httpx.MockTransport(handler))
    doc, diag = await f.fetch(SRC)
    assert diag.outcome == FetchOutcome.OK and calls["n"] == 2


async def test_robots_replaced_by_waf_page_is_blocked():
    waf = "<script>{code:'user_blocked'}</script>Возникла проблема при открытии сайта".encode()
    f = make({"/robots.txt": (200, waf), "/page": (200, b"<html>real</html>")})
    doc, diag = await f.fetch(SRC)
    assert doc is None and diag.outcome == FetchOutcome.BLOCKED


# ---------- этап 7: усиление загрузчика ----------

def make_h(handler, **kw) -> HttpFetcher:
    return HttpFetcher(UA, min_interval_s=0, transport=httpx.MockTransport(handler), **kw)


def redirect_to(location, status=302):
    return httpx.Response(status, headers={"location": location})


async def test_redirect_within_same_site_is_followed_including_www_toggle():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.host == "www.example-bank.test":
            return redirect_to("https://example-bank.test/final")
        return httpx.Response(200, content=b"<html>ok</html>", headers={"content-type": "text/html"})

    doc, diag = await make_h(handler).fetch(SRC)
    assert diag.outcome == FetchOutcome.OK and doc.url == "https://example-bank.test/final"


@pytest.mark.parametrize("target", [
    "https://evil.example.com/x",              # чужой домен
    "https://example-bank.test.evil.com/x",    # похожий домен
    "http://www.example-bank.test/page",       # понижение до http
    "file:///etc/passwd", "ftp://example-bank.test/x",
])
async def test_redirect_off_site_or_downgrade_rejected_and_not_requested(target):
    seen = []

    def handler(req):
        seen.append(str(req.url))
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return redirect_to(target)

    doc, diag = await make_h(handler).fetch(SRC)
    assert doc is None and diag.outcome == FetchOutcome.REDIRECT_REJECTED
    assert not any("evil" in u or u.startswith(("file", "ftp")) for u in seen)  # запрос на чужой адрес не отправлялся


async def test_redirect_loop_is_limited():
    def handler(req):
        return httpx.Response(404) if req.url.path == "/robots.txt" else redirect_to("/page")

    _, diag = await make_h(handler).fetch(SRC)
    assert diag.outcome == FetchOutcome.REDIRECT_REJECTED and "перенаправлений" in diag.error


async def test_size_limit_enforced_while_streaming_without_content_length():
    pulled = {"n": 0}

    async def body():
        for _ in range(1000):
            pulled["n"] += 1
            yield b"x" * 1024

    def handler(req):
        return httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(200, content=body())

    doc, diag = await make_h(handler, max_bytes=10_000).fetch(SRC)
    assert doc is None and diag.outcome == FetchOutcome.TOO_LARGE
    assert pulled["n"] < 50  # поток прерван рано, а не скачан целиком


async def test_declared_content_length_over_limit_rejected_before_reading():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, headers={"content-length": "999999999"}, content=b"x" * 10)

    _, diag = await make_h(handler, max_bytes=1000).fetch(SRC)
    assert diag.outcome == FetchOutcome.TOO_LARGE


async def test_network_errors_retried_three_times_then_reported():
    calls = {"n": 0}

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        calls["n"] += 1
        raise httpx.ConnectTimeout("t")

    _, diag = await make_h(handler).fetch(SRC)
    assert calls["n"] == 3 and diag.outcome == FetchOutcome.NETWORK_ERROR and "попыток: 3" in diag.error


async def test_tls_error_is_not_retried():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        err = httpx.ConnectError("tls")
        err.__cause__ = ssl.SSLCertVerificationError("bad cert")
        raise err

    _, diag = await make_h(handler).fetch(SRC)
    assert diag.outcome == FetchOutcome.TLS_ERROR and calls["n"] == 1


async def test_unexpected_exception_becomes_source_failure():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        raise ZeroDivisionError("bug")

    doc, diag = await make_h(handler).fetch(SRC)
    assert doc is None and diag.outcome == FetchOutcome.INTERNAL_ERROR and "ZeroDivisionError" in diag.error


async def test_adapter_survives_fetcher_crash_on_one_source():
    from bankintel.domain.enums import CollectionStatus
    from bankintel.sources import get_adapter
    from bankintel.sources.base import FetchDiagnostic, FetchedDocument

    class Crashy:
        async def fetch(self, source):
            if source.key == "a":
                raise RuntimeError("boom")
            return FetchedDocument(source.url, b"<html/>"), FetchDiagnostic(source.key, source.url, FetchOutcome.OK, 200)

    res = await get_adapter("generic")("x", Crashy()).collect([SourceRef("a", "https://x.test/a", "d"), SourceRef("b", "https://x.test/b", "d")])
    assert res.status == CollectionStatus.PARTIAL and len(res.documents) == 1
    assert any("internal_error" in m and "RuntimeError" in m for m in res.messages)
