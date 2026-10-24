"""Модель данных.

Принцип: любое извлечённое значение прослеживается до сохранённого документа
(Document -> ProductSnapshot.document_id) с URL и временем проверки.
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bankintel.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Bank(Base):
    __tablename__ = "banks"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    website: Mapped[str] = mapped_column(String(500))
    adapter: Mapped[str] = mapped_column(String(50))
    is_benchmark: Mapped[bool] = mapped_column(Boolean, default=False)  # Сбер — эталон сравнения
    # Подтвердил ли человек, что домен официальный и банк работает в ЛНР.
    domain_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    lnr_presence_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    sources: Mapped[list["Source"]] = relationship(back_populates="bank", cascade="all, delete-orphan")


class Source(Base):
    """Официальный источник данных (страница/PDF) конкретного банка."""

    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("bank_id", "key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    bank_id: Mapped[int] = mapped_column(ForeignKey("banks.id"))
    key: Mapped[str] = mapped_column(String(100))
    url: Mapped[str] = mapped_column(String(1000))
    category: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="todo")
    # fetch — загружаем сами; manual — документы вносит человек (сайт недоступен загрузчику)
    mode: Mapped[str] = mapped_column(String(10), default="fetch", server_default="fetch")
    notes: Mapped[str | None] = mapped_column(Text)

    bank: Mapped[Bank] = relationship(back_populates="sources")


class FetchAttempt(Base):
    """Каждая попытка загрузки, включая неудачные — для диагностики неполноты данных."""

    __tablename__ = "fetch_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    outcome: Mapped[str] = mapped_column(String(30))
    http_status: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)


class Document(Base):
    """Сохранённый исходный документ (HTML/PDF). Тело лежит в файловом хранилище."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    url: Mapped[str] = mapped_column(String(1000))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    content_type: Mapped[str | None] = mapped_column(String(100))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_path: Mapped[str] = mapped_column(String(500))
    size_bytes: Mapped[int] = mapped_column(Integer)
    # fetched — получен загрузчиком; manual_import — внесён человеком (fetched_at = дата сохранения, со слов человека)
    origin: Mapped[str] = mapped_column(String(20), default="fetched", server_default="fetched")
    note: Mapped[str | None] = mapped_column(Text)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("bank_id", "category", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    bank_id: Mapped[int] = mapped_column(ForeignKey("banks.id"))
    category: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(300))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ProductSnapshot(Base):
    """Версия параметров продукта, извлечённая из конкретного документа."""

    __tablename__ = "product_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Извлечённые значения как они указаны в источнике (ставки, сроки, суммы...).
    params: Mapped[dict] = mapped_column(JSON)
    # Дословные цитаты из документа, подтверждающие params.
    evidence: Mapped[dict | None] = mapped_column(JSON)
    extractor: Mapped[str] = mapped_column(String(50))  # "rules" | "llm:<model>" | "manual"
    base_rate_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))


class RegionAvailability(Base):
    __tablename__ = "region_availability"
    __table_args__ = (UniqueConstraint("product_id", "region"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    region: Mapped[str] = mapped_column(String(20), default="LNR")
    status: Mapped[str] = mapped_column(String(20), default="unknown")
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    quote: Mapped[str | None] = mapped_column(Text)  # цитата, подтверждающая статус
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChangeEvent(Base):
    __tablename__ = "change_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    change_type: Mapped[str] = mapped_column(String(20))
    diff: Mapped[dict | None] = mapped_column(JSON)
    snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("product_snapshots.id"))


class CollectionRun(Base):
    """Запуск сбора по банку: итоговый статус и полнота."""

    __tablename__ = "collection_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    bank_id: Mapped[int] = mapped_column(ForeignKey("banks.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20))
    message: Mapped[str | None] = mapped_column(Text)
