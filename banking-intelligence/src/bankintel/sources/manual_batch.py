"""Пакетный ручной импорт: папка сохранённых страниц + манифест `manifest.yaml`.

Тот же принцип, что у `import_document` (мы не обходим защиту сайтов): страницы сохраняет человек, а
здесь он лишь не вводит по команде на каждую. Всё проверяется до записи; повторный запуск безопасен.
"""

import asyncio
import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bankintel.db.models import Bank, Document, Source
from bankintel.sources.manual import CONTENT_TYPES, ManualImportError, import_document

MANIFEST_NAME = "manifest.yaml"
MAX_FILE_BYTES = 20 * 1024 * 1024
# Chrome/Edge пишут в начало сохранённого HTML: <!-- saved from url=(0052)https://... -->
SAVED_FROM = re.compile(rb"<!--\s*saved from url=\(\d+\)(\S+?)\s*-->", re.IGNORECASE)
KEY_OK = re.compile(r"^[a-z0-9][a-z0-9_-]{0,48}$")
Category = Literal["deposit", "savings", "promo"]


class ManifestError(Exception):
    pass


class PageEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file: str
    url: str | None = None
    source_key: str | None = None
    category: Category | None = None
    captured_at: str | None = None
    note: str | None = None


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    captured_at: str | None = None
    category: Category | None = None
    note: str | None = None
    pages: list[PageEntry]


@dataclass
class PlannedPage:
    path: Path
    url: str
    source_key: str
    category: str
    captured_at: datetime
    note: str | None


@dataclass
class PageResult:
    file: str
    status: Literal["imported", "unchanged", "rejected"]
    detail: str = ""


@dataclass
class BatchReport:
    results: list[PageResult] = field(default_factory=list)
    unlisted: list[str] = field(default_factory=list)
    new_sources: list[PlannedPage] = field(default_factory=list)

    @property
    def rejected(self) -> int:
        return sum(r.status == "rejected" for r in self.results)

    @property
    def imported(self) -> int:
        return sum(r.status == "imported" for r in self.results)


def load_manifest(path: Path) -> Manifest:
    if not path.is_file():
        raise ManifestError(f"Манифест не найден: {path}. Создайте шаблон: import-dir --init")
    try:
        # BaseLoader: все скаляры остаются строками — дата с часовым поясом не превращается в «наивную»
        raw = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)  # noqa: S506
        return Manifest.model_validate(raw)
    except (yaml.YAMLError, ValidationError, TypeError) as exc:
        raise ManifestError(f"Манифест некорректен: {exc}") from None


def _parse_when(value: str | None, file: Path) -> datetime:
    if not value:
        raise ManifestError("не указана дата сохранения (captured_at; можно значение mtime — время изменения файла)")
    if value.strip().lower() == "mtime":
        return datetime.fromtimestamp(file.stat().st_mtime, UTC)
    try:
        when = datetime.fromisoformat(value.strip())
    except ValueError:
        raise ManifestError(f"дата {value!r} не в формате ISO, пример: 2026-10-24T12:00+03:00") from None
    if when.tzinfo is None:
        raise ManifestError("в дате нет часового пояса (пример: 2026-10-24T12:00+03:00)")
    return when.astimezone(UTC)  # в UTC, чтобы значение не зависело от того, хранит ли СУБД часовой пояс


def saved_from_url(path: Path) -> str | None:
    if path.suffix.lower() not in (".html", ".htm"):
        return None
    with path.open("rb") as fh:
        m = SAVED_FROM.search(fh.read(4096))
    return m.group(1).decode("ascii", "ignore") if m else None


def _inside(directory: Path, name: str) -> Path:
    target = (directory / name).resolve()
    if directory.resolve() not in target.parents:
        raise ManifestError("файл должен лежать внутри папки импорта")
    if not target.is_file():
        raise ManifestError("файл не найден")
    if target.stat().st_size > MAX_FILE_BYTES:
        raise ManifestError(f"файл больше {MAX_FILE_BYTES // 1024 // 1024} МБ")
    return target


def plan_pages(directory: Path, manifest: Manifest) -> tuple[list[PlannedPage], list[PageResult], list[str]]:
    """Чистая проверка без БД: возвращает (к импорту, отклонённые, файлы вне манифеста)."""
    planned: list[PlannedPage] = []
    rejected: list[PageResult] = []
    seen_keys: dict[str, str] = {}
    listed: set[Path] = set()
    for e in manifest.pages:
        try:
            path = _inside(directory, e.file)
            listed.add(path)
            if path.suffix.lower() not in CONTENT_TYPES:
                raise ManifestError(f"поддерживаются {sorted(CONTENT_TYPES)}")
            url = e.url or saved_from_url(path)
            if not url or url.upper().startswith("ЗАПОЛНИТЕ"):
                raise ManifestError("не указан url (и Chrome не оставил в файле комментарий «saved from url»)")
            key = e.source_key or re.sub(r"[^a-z0-9_-]+", "-", path.stem.lower()).strip("-")
            if not KEY_OK.match(key):
                raise ManifestError(f"source_key {key!r} недопустим (a-z, 0-9, _ и -)")
            if key in seen_keys:
                raise ManifestError(f"source_key {key!r} уже использован для {seen_keys[key]}: один источник — одна страница")
            category = e.category or manifest.category
            if category is None:
                raise ManifestError("не указана category (deposit/savings/promo)")
            when = _parse_when(e.captured_at or manifest.captured_at, path)
            seen_keys[key] = e.file
            planned.append(PlannedPage(path, url, key, category, when, e.note or manifest.note))
        except ManifestError as exc:
            rejected.append(PageResult(e.file, "rejected", str(exc)))
    unlisted = sorted(
        p.name for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in CONTENT_TYPES and p.resolve() not in listed
    )
    return planned, rejected, unlisted


async def _latest_manual_sha(session: AsyncSession, bank_id: int, key: str) -> tuple[str | None, str | None]:
    """(sha256 последнего ручного документа источника, URL источника)."""
    src = await session.scalar(select(Source).where(Source.bank_id == bank_id, Source.key == key))
    if src is None:
        return None, None
    sha = await session.scalar(
        select(Document.sha256).where(Document.source_id == src.id, Document.origin == "manual_import")
        .order_by(Document.fetched_at.desc(), Document.id.desc()).limit(1)
    )
    return sha, src.url


async def import_directory(
    session: AsyncSession, bank: Bank, directory: Path, manifest: Manifest, *,
    official_hosts: set[str], raw_root: Path, dry_run: bool = False,
) -> BatchReport:
    planned, rejected, unlisted = await asyncio.to_thread(plan_pages, directory, manifest)
    report = BatchReport(results=list(rejected), unlisted=unlisted)
    bank_id = bank.id
    for page in planned:
        name = page.path.name
        sha = hashlib.sha256(await asyncio.to_thread(page.path.read_bytes)).hexdigest()
        prev_sha, prev_url = await _latest_manual_sha(session, bank_id, page.source_key)
        if prev_url is not None and prev_url != page.url:
            report.results.append(PageResult(name, "rejected", f"источник {page.source_key!r} уже привязан к другому URL: {prev_url}"))
            continue
        if prev_sha == sha:
            report.results.append(PageResult(name, "unchanged", "тот же файл уже импортирован"))
            continue
        try:
            if dry_run:
                await asyncio.to_thread(_check_only, page, official_hosts)
            else:
                await import_document(
                    session, bank, source_key=page.source_key, url=page.url, category=page.category,
                    file_path=page.path, captured_at=page.captured_at, official_hosts=official_hosts,
                    raw_root=raw_root, note=page.note,
                )
        except ManualImportError as exc:  # все проверки срабатывают до записи в БД — откат не нужен
            report.results.append(PageResult(name, "rejected", str(exc)))
            continue
        report.results.append(PageResult(name, "imported", "проверен (пробный запуск, не записан)" if dry_run else "записан"))
        if prev_url is None:
            report.new_sources.append(page)
    return report


def _check_only(page: PlannedPage, official_hosts: set[str]) -> None:
    """Те же проверки, что в import_document, но без записи (для --dry-run)."""
    from bankintel.sources.fetcher import looks_blocked
    from bankintel.sources.manual import _host_ok

    if not _host_ok(page.url, official_hosts):
        raise ManualImportError(f"URL {page.url} не входит в официальные домены банка {sorted(official_hosts)}")
    content = page.path.read_bytes()
    if not content:
        raise ManualImportError("Файл пустой")
    if CONTENT_TYPES[page.path.suffix.lower()] == "text/html" and looks_blocked(200, content):
        raise ManualImportError("Файл похож на страницу блокировки/капчи, а не на страницу банка")


def write_manifest_template(directory: Path, *, category: str | None = None) -> tuple[Path, int]:
    """Шаблон манифеста по файлам папки; url подставляется, если Chrome оставил «saved from url»."""
    target = directory / MANIFEST_NAME
    if target.exists():
        raise ManifestError(f"{target} уже существует — шаблон не перезаписываю")
    files = sorted(p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in CONTENT_TYPES)
    if not files:
        raise ManifestError(f"В {directory} нет .html/.htm/.pdf — сначала сохраните страницы")
    lines = [
        "# Манифест ручного импорта. Заполните пропуски и запустите: bankintel import-dir --bank <банк> --dir <папка>",
        "# Даты с часовым поясом, например 2026-10-24T12:00+03:00; mtime = время изменения файла (когда сохранили).",
        "captured_at: mtime",
        f"category: {category or 'deposit'}   # deposit | savings | promo; можно переопределить у страницы",
        "pages:",
    ]
    for f in files:
        url = saved_from_url(f)
        lines.append(f"  - file: {f.name}")
        lines.append(f"    url: {url}" if url else "    url: ЗАПОЛНИТЕ  # адрес из адресной строки браузера")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target, len(files)
