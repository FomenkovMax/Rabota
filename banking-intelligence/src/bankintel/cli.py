import argparse
import asyncio

from bankintel.config import get_settings
from bankintel.db.session import make_engine, make_session_factory
from bankintel.registry.loader import load_config, sync_registry


async def _seed() -> None:
    settings = get_settings()
    cfg = load_config(settings.config_dir)
    engine = make_engine(settings.database_url)
    try:
        async with make_session_factory(engine)() as session:
            print(await sync_registry(session, cfg))
    finally:
        await engine.dispose()


async def _collect(include_todo: bool, with_details: bool = False) -> None:
    from sqlalchemy import select

    from bankintel.collector import collect_all
    from bankintel.db.models import Bank
    from bankintel.details import collect_details
    from bankintel.sources.fetcher import build_fetcher

    settings = get_settings()
    engine = make_engine(settings.database_url)
    fetcher = build_fetcher(settings)
    try:
        async with make_session_factory(engine)() as session:
            for bank, run in await collect_all(session, fetcher, settings.raw_storage_dir, include_todo=include_todo):
                print(f"{bank.slug:8} {run.status:16} {run.message or ''}")
            if with_details:
                for bank in (await session.scalars(select(Bank).order_by(Bank.id))).all():
                    if bank.adapter != "generic":
                        run = await collect_details(session, bank, fetcher, settings.raw_storage_dir)
                        print(f"{bank.slug:8} details {run.status:9} {run.message or ''}")
    finally:
        await fetcher.aclose()
        await engine.dispose()


async def _discover(slug: str) -> None:
    from sqlalchemy import select

    from bankintel.db.models import Bank
    from bankintel.registry.schemas import BankConfig
    from bankintel.sources.base import SourceRef
    from bankintel.sources.discovery import discover_links
    from bankintel.sources.fetcher import build_fetcher

    settings = get_settings()
    cfg = next((b for b in load_config(settings.config_dir).banks if b.slug == slug), None)
    if cfg is None:
        raise SystemExit(f"Банк {slug!r} не найден в config/banks.yaml")
    fetcher = build_fetcher(settings)
    try:
        doc, diag = await fetcher.fetch(SourceRef("site_root", str(cfg.website), "discovery"))
    finally:
        await fetcher.aclose()
    if doc is None:
        raise SystemExit(f"Не удалось загрузить {cfg.website}: {diag.outcome.value} {diag.error or ''}")
    for c in discover_links(doc.content, doc.url, cfg.official_hosts):
        print(f"{c.category:8} {c.url}  | {c.anchor}")
    print("\nЭто только кандидаты. Проверьте вручную и добавьте в config/sources.yaml со status: active.")


async def _import_doc(args) -> None:
    from datetime import datetime
    from pathlib import Path

    from sqlalchemy import select

    from bankintel.db.models import Bank
    from bankintel.sources.manual import ManualImportError, import_document

    settings = get_settings()
    cfg = next((b for b in load_config(settings.config_dir).banks if b.slug == args.bank), None)
    if cfg is None:
        raise SystemExit(f"Банк {args.bank!r} не найден в config/banks.yaml")
    engine = make_engine(settings.database_url)
    try:
        async with make_session_factory(engine)() as session:
            bank = await session.scalar(select(Bank).where(Bank.slug == args.bank))
            if bank is None:
                raise SystemExit("Банка нет в БД: выполните bankintel seed")
            try:
                doc = await import_document(
                    session, bank, source_key=args.source_key, url=args.url, category=args.category,
                    file_path=Path(args.file), captured_at=datetime.fromisoformat(args.captured_at),
                    official_hosts=cfg.official_hosts, raw_root=settings.raw_storage_dir, note=args.note,
                )
            except ManualImportError as exc:
                raise SystemExit(f"Импорт отклонён: {exc}")
            print(f"Импортировано: document_id={doc.id} sha256={doc.sha256[:12]} {doc.size_bytes} байт")
            print("Добавьте источник в config/sources.yaml (mode: manual, status: active), чтобы он не потерялся при seed:")
            print(f"  - bank: {args.bank}\n    key: {args.source_key}\n    url: {args.url}\n    category: {args.category}\n    status: active\n    mode: manual")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="bankintel")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed", help="загрузить реестр банков и источников из config/ в БД")
    sub.add_parser("probe", help="проверить доступность корня сайта каждого банка (сохраняет диагностику)")
    r = sub.add_parser("refresh", help="собрать данные по активным (подтверждённым) источникам")
    r.add_argument("--details", action="store_true", help="дополнительно загрузить страницы продуктов и извлечь условия")
    d = sub.add_parser("discover", help="найти кандидатов продуктовых страниц на сайте банка")
    d.add_argument("bank")
    i = sub.add_parser("import-doc", help="внести вручную сохранённую страницу/PDF банка (если сайт недоступен загрузчику)")
    i.add_argument("--bank", required=True)
    i.add_argument("--source-key", required=True)
    i.add_argument("--url", required=True, help="публичный URL, откуда сохранена страница")
    i.add_argument("--category", required=True, choices=["deposit", "savings", "promo"])
    i.add_argument("--file", required=True)
    i.add_argument("--captured-at", required=True, help="когда сохранено, ISO с часовым поясом: 2026-10-24T12:00+03:00")
    i.add_argument("--note")
    sub.add_parser("bot", help="запустить Telegram-бота")
    args = parser.parse_args()
    if args.cmd == "seed":
        asyncio.run(_seed())
    elif args.cmd == "probe":
        asyncio.run(_collect(include_todo=True))
    elif args.cmd == "refresh":
        asyncio.run(_collect(include_todo=False, with_details=args.details))
    elif args.cmd == "discover":
        asyncio.run(_discover(args.bank))
    elif args.cmd == "import-doc":
        asyncio.run(_import_doc(args))
    elif args.cmd == "bot":
        from bankintel.bot.app import main as bot_main

        bot_main()


if __name__ == "__main__":
    main()
