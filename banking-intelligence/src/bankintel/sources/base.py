"""Базовый интерфейс адаптера банка.

Адаптер независим от остальных: знает только как получить и разобрать
документы своего банка. Сохранение в БД, AI и отчёты — вне адаптера.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from bankintel.domain.enums import (
    AvailabilityStatus,
    CollectionStatus,
    FetchOutcome,
    ProductCategory,
)


@dataclass(frozen=True)
class SourceRef:
    key: str
    url: str
    category: str


@dataclass
class FetchedDocument:
    url: str
    content: bytes
    content_type: str | None = None
    http_status: int = 200
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    document_id: int | None = None  # задан, если документ уже сохранён в БД (ручной импорт)


@dataclass
class FetchDiagnostic:
    """Результат попытки загрузки. Сохраняется всегда — в том числе при ошибке."""

    source_key: str
    url: str
    outcome: FetchOutcome
    http_status: int | None = None
    error: str | None = None
    duration_ms: int | None = None


@dataclass
class ExtractedProduct:
    """Продукт, извлечённый из документа. Значения — как в источнике, без пересчётов."""

    name: str
    category: ProductCategory
    params: dict
    evidence: dict[str, str]  # поле -> дословная цитата
    lnr_status: AvailabilityStatus = AvailabilityStatus.UNKNOWN
    lnr_quote: str | None = None


@dataclass
class CollectionResult:
    bank_slug: str
    status: CollectionStatus
    documents: list[tuple[SourceRef, FetchedDocument]] = field(default_factory=list)
    diagnostics: list[FetchDiagnostic] = field(default_factory=list)
    products: list[tuple[SourceRef, FetchedDocument, ExtractedProduct]] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


class Fetcher(Protocol):
    """Загрузчик документов (реализация — этап 2: httpx + robots.txt + Playwright)."""

    async def fetch(self, source: SourceRef) -> tuple[FetchedDocument | None, FetchDiagnostic]: ...


class BankAdapter(ABC):
    slug: str = ""

    def __init__(self, bank_slug: str, fetcher: Fetcher | None = None):
        self.bank_slug = bank_slug
        self.fetcher = fetcher

    @abstractmethod
    def parse(self, source: SourceRef, doc: FetchedDocument) -> list[ExtractedProduct]:
        """Разбор одного документа. Не должен выдумывать значения: нет данных — нет поля."""

    async def collect(self, sources: list[SourceRef]) -> CollectionResult:
        """Шаблонный метод: загрузка -> разбор -> итоговый статус полноты."""
        result = CollectionResult(bank_slug=self.bank_slug, status=CollectionStatus.OK)
        if not sources:
            result.status = CollectionStatus.FAILED
            result.messages.append("Нет активных источников для банка")
            return result
        if self.fetcher is None:
            result.status = CollectionStatus.NOT_IMPLEMENTED
            result.messages.append("Загрузчик документов не подключён")
            return result

        failed = 0
        for src in sources:
            doc, diag = await self.fetcher.fetch(src)
            result.diagnostics.append(diag)
            if doc is None or diag.outcome != FetchOutcome.OK:
                failed += 1
                result.messages.append(f"{src.key}: {diag.outcome.value} {diag.error or ''}".strip())
                continue
            result.documents.append((src, doc))  # документ сохраняем, даже если разбор не удался
            try:
                products = self.parse(src, doc)
            except Exception as exc:  # вёрстка изменилась и т.п.: фиксируем, не роняем весь сбор
                failed += 1
                result.messages.append(f"{src.key}: parse_error {type(exc).__name__}: {exc}"[:500])
                continue
            for product in products:
                result.products.append((src, doc, product))

        if failed == len(sources):
            result.status = CollectionStatus.FAILED
        elif failed:
            result.status = CollectionStatus.PARTIAL
        return result


_ADAPTERS: dict[str, type[BankAdapter]] = {}


def register_adapter(name: str):
    def deco(cls: type[BankAdapter]) -> type[BankAdapter]:
        cls.slug = name
        _ADAPTERS[name] = cls
        return cls

    return deco


def get_adapter(name: str) -> type[BankAdapter]:
    try:
        return _ADAPTERS[name]
    except KeyError:
        raise KeyError(f"Адаптер {name!r} не зарегистрирован") from None
