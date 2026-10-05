"""CA-бандл с корнем Минцифры и проверка TLS. Проверка сертификатов не отключается никогда."""

from __future__ import annotations

import ssl
from dataclasses import dataclass
from pathlib import Path

import httpx

from lnrbank.config import Settings, load_secrets

# SHA-256 корня «Russian Trusted Root CA» (Минцифры).
# Сверен 05.10.2026 с gu-st.ru и цепочками сайтов банков.
MINTSIFRY_ROOT_SHA256 = (
    "D2:6D:2D:02:31:B7:C3:9F:92:CC:73:85:12:BA:54:10:35:19:"
    "E4:40:5D:68:B5:BD:70:3E:97:88:CA:8E:CF:31"
)


class CABundleMissing(RuntimeError):
    pass


def ca_bundle_path(settings: Settings) -> Path:
    override = load_secrets().lnrbank_ca_bundle
    path = override or settings.resolve(settings.tls.ca_bundle)
    if not path.is_file():
        raise CABundleMissing(
            f"Нет CA-бандла {path}. Запусти scripts/install_certs.sh (ставит корень Минцифры)."
        )
    return path


def ssl_context(settings: Settings) -> ssl.SSLContext:
    return ssl.create_default_context(cafile=str(ca_bundle_path(settings)))


@dataclass
class TLSResult:
    host: str
    ok: bool
    detail: str


def check_tls(settings: Settings, timeout: float = 20.0) -> list[TLSResult]:
    """HEAD к каждому хосту с полной проверкой сертификата через CA-бандл."""
    ctx = ssl_context(settings)
    results = []
    with httpx.Client(verify=ctx, timeout=timeout, trust_env=True) as client:
        for host in settings.tls.check_hosts:
            try:
                resp = client.head(f"https://{host}/")
                results.append(TLSResult(host, True, f"HTTP {resp.status_code}"))
            except httpx.ConnectError as exc:
                results.append(TLSResult(host, False, str(exc)[:200]))
            except httpx.HTTPError as exc:
                results.append(TLSResult(host, False, type(exc).__name__))
    return results
