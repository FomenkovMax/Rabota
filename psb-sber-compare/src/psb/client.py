"""HTTP-клиент для psbank.ru.

Две особенности сайта, ради которых нужен отдельный клиент:

1. Сертификат psbank.ru выпущен НУЦ Минцифры («Russian Trusted Root CA»).
   Этого корня нет в стандартном наборе `certifi`, поэтому requests падает
   с CERTIFICATE_VERIFY_FAILED. Мы добавляем корень из `certs/` к системному
   набору — проверку сертификата НЕ отключаем.

2. Регион выбирается cookie `geoId` с JSON внутри. Без неё сайт определяет
   город по IP, и для ЛНР получить условия невозможно.
"""

from __future__ import annotations

import json
import logging
import ssl
import tempfile
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

import certifi
import requests

log = logging.getLogger(__name__)

BASE_URL = "https://www.psbank.ru"
CERT_DIR = Path(__file__).resolve().parents[2] / "certs"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class Region:
    """Регион присутствия в терминах справочника ПСБ."""

    city_id: int
    city_name: str
    # hierarchyIds: город → область/республика → страна
    hierarchy: tuple[int, ...]

    @property
    def geo_cookie(self) -> str:
        payload = {
            "cityId": self.city_id,
            "cityName": self.city_name,
            "cityFilter": ",".join(str(i) for i in self.hierarchy),
        }
        return urllib.parse.quote(json.dumps(payload, ensure_ascii=False))


# Проверено вживую: смена cookie меняет ставки по вкладам.
LUGANSK = Region(city_id=811307, city_name="Луганск", hierarchy=(811307, 811561, 811577))
MOSCOW = Region(city_id=811354, city_name="Москва", hierarchy=(811354, 819319, 811577))

REGIONS = {"lugansk": LUGANSK, "moscow": MOSCOW}


def build_ca_bundle() -> str:
    """Склеивает certifi с российскими корнями во временный файл.

    Возвращает путь, который можно передать в `verify=`. Файл живёт до конца
    процесса — этого достаточно, пересоздавать на каждый запрос смысла нет.
    """
    extra = sorted(CERT_DIR.glob("*.pem"))
    if not extra:
        log.warning("В %s нет .pem — используем только certifi, возможна ошибка TLS", CERT_DIR)
        return certifi.where()

    chunks = [Path(certifi.where()).read_text(encoding="utf-8")]
    for path in extra:
        chunks.append(path.read_text(encoding="utf-8"))

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".pem", prefix="psb-ca-", delete=False, encoding="utf-8"
    )
    tmp.write("\n".join(chunks))
    tmp.close()
    return tmp.name


class PageNotFound(RuntimeError):
    """Узел есть в карте сайта, но страницы по этому адресу нет.

    Карта сайта — это дерево CMS, и часть его узлов служебные: раздел может
    существовать как контейнер, а отдельной страницы под ним не быть.
    Такой случай — норма, а не сбой сети.
    """


class PsbClient:
    """Тонкая обёртка над requests.Session с регионом и ретраями."""

    def __init__(
        self,
        region: Region = LUGANSK,
        *,
        timeout: int = 30,
        retries: int = 3,
        pause: float = 1.0,
    ) -> None:
        self.region = region
        self.timeout = timeout
        self.retries = retries
        self.pause = pause
        self.ca_bundle = build_ca_bundle()

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9",
            }
        )
        self.session.cookies.set("geoId", region.geo_cookie, domain="www.psbank.ru")

    def get(self, path: str) -> str:
        """Забирает страницу. Между запросами выдерживает паузу.

        Пауза не для обхода защиты, а из вежливости к чужому серверу:
        полный обход каталога — это сотни запросов подряд.
        """
        url = path if path.startswith("http") else f"{BASE_URL}{path}"
        last_error: Exception | None = None

        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.get(url, timeout=self.timeout, verify=self.ca_bundle)
                response.raise_for_status()
                time.sleep(self.pause)
                return response.text
            except requests.exceptions.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                # 404 и прочие клиентские ошибки от повтора не исправятся,
                # а каждая попытка с бэкоффом стоит секунд четырнадцать.
                if status == 404:
                    raise PageNotFound(f"Страницы нет: {url}") from exc
                if 400 <= status < 500 and status != 429:
                    raise RuntimeError(f"{url} → HTTP {status}") from exc
                last_error = exc
                backoff = 2 ** attempt
                log.warning("Запрос %s вернул HTTP %s (%s/%s). Ждём %ss",
                            url, status, attempt, self.retries, backoff)
                time.sleep(backoff)
            except requests.exceptions.SSLError as exc:
                # Ретраить бессмысленно: сертификат не станет доверенным сам по себе.
                raise RuntimeError(
                    "Ошибка TLS при обращении к psbank.ru.\n"
                    "Сайт использует сертификат НУЦ Минцифры. Проверь, что в папке\n"
                    f"{CERT_DIR} лежит russian_trusted_ca.pem\n"
                    "Скачать официально: https://www.gosuslugi.ru/crt"
                ) from exc
            except requests.RequestException as exc:
                last_error = exc
                backoff = 2 ** attempt
                log.warning("Запрос %s не удался (%s/%s): %s. Ждём %ss",
                            url, attempt, self.retries, exc, backoff)
                time.sleep(backoff)

        raise RuntimeError(f"Не удалось загрузить {url} после {self.retries} попыток") from last_error

    def __enter__(self) -> "PsbClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.session.close()
