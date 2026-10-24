"""Загрузчик официальных страниц: robots.txt, rate limit, диагностика, без обхода защиты."""

import asyncio
import ssl
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from bankintel.domain.enums import FetchOutcome
from bankintel.sources.base import FetchDiagnostic, FetchedDocument, SourceRef

# Признаки антибот-страниц. Нашли — фиксируем BLOCKED и НЕ пытаемся обойти.
BLOCK_MARKERS = (
    "captcha", "recaptcha", "hcaptcha", "вы не робот", "подтвердите, что вы не робот",
    "access denied", "ddos-guard", "just a moment", "cf-chl",
    "user_blocked", "возникла проблема при открытии сайта",
)


class BlockedError(Exception):
    """Антибот отдал страницу блокировки вместо ожидаемого содержимого."""


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def _is_tls_error(exc: BaseException) -> bool:
    while exc is not None:
        if isinstance(exc, ssl.SSLCertVerificationError):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def looks_blocked(status: int, body: bytes) -> bool:
    """403/429 или короткая страница с маркерами капчи/антибота (большие страницы не проверяем)."""
    if status in (403, 429):
        return True
    if len(body) >= 20_000:
        return False
    head = body.lower().decode("utf-8", errors="ignore")
    return any(m in head for m in BLOCK_MARKERS)


class HttpFetcher:
    def __init__(
        self,
        user_agent: str,
        *,
        min_interval_s: float = 2.0,
        timeout_s: float = 20.0,
        max_bytes: int = 10_000_000,
        extra_ca_bundle: Path | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        verify: ssl.SSLContext | bool = True
        if extra_ca_bundle is not None:
            verify = ssl.create_default_context()  # системные CA + дополнительный файл
            verify.load_verify_locations(cafile=str(extra_ca_bundle))
        self._client = httpx.AsyncClient(
            headers={"User-Agent": user_agent},
            timeout=timeout_s,
            follow_redirects=True,
            verify=verify,
            transport=transport,
        )
        self._ua = user_agent
        self._min_interval = min_interval_s
        self._max_bytes = max_bytes
        self._robots: dict[str, RobotFileParser | None] = {}
        self._last_hit: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _throttled_get(self, url: str) -> httpx.Response:
        host = urlparse(url).netloc
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            wait = self._last_hit.get(host, 0) + self._min_interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                return await self._client.get(url)
            finally:
                self._last_hit[host] = time.monotonic()

    async def _robots_for(self, url: str) -> RobotFileParser | None:
        """None = robots.txt недоступен (401/403/5xx) -> консервативно запрещаем."""
        p = urlparse(url)
        origin = f"{p.scheme}://{p.netloc}"
        if origin in self._robots:
            return self._robots[origin]
        rp = RobotFileParser()
        resp = await self._throttled_get(origin + "/robots.txt")
        if looks_blocked(resp.status_code, resp.content):
            raise BlockedError("robots.txt подменён страницей блокировки (WAF/антибот)")
        if resp.status_code in (404, 410):
            rp.parse([])  # robots.txt отсутствует -> разрешено
        elif resp.status_code >= 400:
            rp = None  # 401/403/5xx: доступ закрыт или сбой -> консервативно запрещаем
        else:
            rp.parse(resp.text.splitlines())
        self._robots[origin] = rp
        return rp

    async def fetch(self, source: SourceRef) -> tuple[FetchedDocument | None, FetchDiagnostic]:
        start = time.monotonic()

        def diag(outcome, status=None, error=None):
            return FetchDiagnostic(source.key, source.url, outcome, status, error, _ms(start))

        resp = None
        for attempt in (1, 2):  # одна повторная попытка только для сетевых сбоев
            try:
                rp = await self._robots_for(source.url)
                if rp is None or not rp.can_fetch(self._ua, source.url):
                    return None, diag(FetchOutcome.ROBOTS_DISALLOWED, error="robots.txt запрещает или недоступен (401/403/5xx)")
                resp = await self._throttled_get(source.url)
                break
            except BlockedError as exc:
                return None, diag(FetchOutcome.BLOCKED, error=str(exc))
            except httpx.HTTPError as exc:
                if _is_tls_error(exc):
                    return None, diag(FetchOutcome.TLS_ERROR, error=f"{type(exc).__name__}: {exc!r}"[:500])
                if attempt == 2:
                    return None, diag(FetchOutcome.NETWORK_ERROR, error=f"{type(exc).__name__}: {exc!r} (попыток: 2)"[:500])
                await asyncio.sleep(self._min_interval)

        body = resp.content
        if len(body) > self._max_bytes:
            return None, diag(FetchOutcome.TOO_LARGE, resp.status_code, f"{len(body)} байт")
        if looks_blocked(resp.status_code, body):
            return None, diag(FetchOutcome.BLOCKED, resp.status_code, "антибот/капча/403 — не обходим")
        if resp.status_code >= 400:
            return None, diag(FetchOutcome.HTTP_ERROR, resp.status_code)
        doc = FetchedDocument(
            url=str(resp.url), content=body, content_type=resp.headers.get("content-type"), http_status=resp.status_code
        )
        return doc, diag(FetchOutcome.OK, resp.status_code)


def build_fetcher(settings) -> HttpFetcher:
    return HttpFetcher(
        settings.user_agent,
        min_interval_s=settings.fetch_min_interval_s,
        timeout_s=settings.fetch_timeout_s,
        max_bytes=settings.fetch_max_bytes,
        extra_ca_bundle=settings.extra_ca_bundle,
    )
