"""Загрузчик официальных страниц: robots.txt, rate limit, диагностика, без обхода защиты."""

import asyncio
import logging
import random
import ssl
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse
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


log = logging.getLogger("bankintel.fetcher")
MAX_REDIRECTS = 5
MAX_ATTEMPTS = 3  # попыток при сетевых сбоях (TLS и блокировки не повторяются)
REDIRECT_CODES = (301, 302, 303, 307, 308)


class BlockedError(Exception):
    """Антибот отдал страницу блокировки вместо ожидаемого содержимого."""


class ResponseTooLarge(Exception):
    pass


class RedirectRejected(Exception):
    pass


@dataclass
class _Response:
    status_code: int
    headers: httpx.Headers
    content: bytes
    url: str

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


def _site(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


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
            follow_redirects=False,  # редиректы обрабатываем сами: только в пределах сайта
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

    async def _stream_once(self, url: str) -> _Response:
        """Один запрос с паузой между обращениями к хосту и жёстким лимитом размера (читаем потоком)."""
        host = urlparse(url).netloc
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            wait = self._last_hit.get(host, 0) + self._min_interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                async with self._client.stream("GET", url) as r:
                    declared = r.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > self._max_bytes:
                        raise ResponseTooLarge(f"Content-Length {declared} байт")
                    chunks, total = [], 0
                    async for chunk in r.aiter_bytes():
                        total += len(chunk)
                        if total > self._max_bytes:
                            raise ResponseTooLarge(f"больше {self._max_bytes} байт")
                        chunks.append(chunk)
                    return _Response(r.status_code, r.headers, b"".join(chunks), str(r.url))
            finally:
                self._last_hit[host] = time.monotonic()

    async def _get(self, url: str) -> _Response:
        """GET с ручной обработкой редиректов: только тот же сайт (с/без www), без понижения https->http."""
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            resp = await self._stream_once(current)
            location = resp.headers.get("location")
            if resp.status_code not in REDIRECT_CODES or not location:
                return resp
            nxt = urljoin(current, location)
            if urlparse(nxt).scheme not in ("http", "https") or _site(nxt) != _site(url):
                raise RedirectRejected(f"редирект за пределы сайта: {nxt[:200]}")
            if urlparse(current).scheme == "https" and urlparse(nxt).scheme != "https":
                raise RedirectRejected("редирект с https на http")
            current = nxt
        raise RedirectRejected(f"больше {MAX_REDIRECTS} перенаправлений подряд")

    async def _robots_for(self, url: str) -> RobotFileParser | None:
        """None = robots.txt недоступен (401/403/5xx) -> консервативно запрещаем."""
        p = urlparse(url)
        origin = f"{p.scheme}://{p.netloc}"
        if origin in self._robots:
            return self._robots[origin]
        rp = RobotFileParser()
        resp = await self._get(origin + "/robots.txt")
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
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                rp = await self._robots_for(source.url)
                if rp is None or not rp.can_fetch(self._ua, source.url):
                    return None, diag(FetchOutcome.ROBOTS_DISALLOWED, error="robots.txt запрещает или недоступен (401/403/5xx)")
                resp = await self._get(source.url)
                break
            except BlockedError as exc:
                return None, diag(FetchOutcome.BLOCKED, error=str(exc))
            except ResponseTooLarge as exc:
                return None, diag(FetchOutcome.TOO_LARGE, error=str(exc))
            except RedirectRejected as exc:
                return None, diag(FetchOutcome.REDIRECT_REJECTED, error=str(exc))
            except httpx.HTTPError as exc:
                if _is_tls_error(exc):
                    return None, diag(FetchOutcome.TLS_ERROR, error=f"{type(exc).__name__}: {exc!r}"[:500])
                if attempt == MAX_ATTEMPTS:
                    return None, diag(FetchOutcome.NETWORK_ERROR, error=f"{type(exc).__name__}: {exc!r} (попыток: {attempt})"[:500])
                # экспоненциальная пауза с небольшим разбросом
                await asyncio.sleep(self._min_interval * 2 ** (attempt - 1) * (1 + random.random() * 0.25))  # noqa: S311 — разброс паузы, не криптография
            except Exception as exc:  # непредвиденное: фиксируем как сбой источника, а не роняем весь сбор
                log.exception("Непредвиденная ошибка загрузки %s", source.url)
                return None, diag(FetchOutcome.INTERNAL_ERROR, error=f"{type(exc).__name__}: {exc}"[:500])

        body = resp.content
        if looks_blocked(resp.status_code, body):
            return None, diag(FetchOutcome.BLOCKED, resp.status_code, "антибот/капча/403 — не обходим")
        if resp.status_code >= 400:
            return None, diag(FetchOutcome.HTTP_ERROR, resp.status_code)
        doc = FetchedDocument(
            url=resp.url, content=body, content_type=resp.headers.get("content-type"), http_status=resp.status_code
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
