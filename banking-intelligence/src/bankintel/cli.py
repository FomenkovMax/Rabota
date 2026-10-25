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


async def _report(out: str) -> None:
    from pathlib import Path

    from bankintel.reports.dataset import DatasetError
    from bankintel.reports.service import generate_reports

    settings = get_settings()
    engine = make_engine(settings.database_url)
    try:
        async with make_session_factory(engine)() as session:
            try:
                bundle = await generate_reports(session, Path(out))
            except DatasetError as exc:
                raise SystemExit(str(exc)) from None
        print(f"Набор данных {bundle.dataset_id}")
        for fmt, path in bundle.paths.items():
            print(f"  {fmt:5} {path} ({path.stat().st_size // 1024} КБ)")
    finally:
        await engine.dispose()


def _monitor_once() -> None:
    from bankintel.cycle import redis_lock
    from bankintel.tasks import _cycle

    with redis_lock(get_settings().redis_url) as got:
        if not got:
            raise SystemExit("Цикл мониторинга уже выполняется (замок в Redis)")
        print(asyncio.run(_cycle()))


async def _changes(days: int) -> None:
    from datetime import UTC, datetime, timedelta

    from bankintel.monitor import monitoring_status, recent_changes

    engine = make_engine(get_settings().database_url)
    try:
        async with make_session_factory(engine)() as session:
            st = await monitoring_status(session)
            print(f"Наблюдение с {st['since']}, сравнений с предыдущим запуском: {st['comparisons']}")
            items = await recent_changes(session, datetime.now(UTC) - timedelta(days=days))
            for it in items:
                print(f"{it['detected_at'][:16]} [{it['severity']}] {it['text']}")
            if not items:
                print("Изменений нет" + (" (пока только базовая линия)" if not st["comparisons"] else ""))
    finally:
        await engine.dispose()


async def _prune(args) -> None:
    from bankintel.retention import apply_prune, plan_prune

    settings = get_settings()
    engine = make_engine(settings.database_url)
    try:
        async with make_session_factory(engine)() as session:
            plan = await plan_prune(session, keep_snapshots=args.keep_snapshots, attempts_days=args.attempts_days, documents_days=args.documents_days)
            print("План очистки:", plan.summary())
            if args.apply:
                print("Удалено:", await apply_prune(session, plan, settings.raw_storage_dir))
            else:
                print("Это пробный запуск, ничего не удалено. Для удаления добавьте --apply.")
    finally:
        await engine.dispose()


async def _ai_extract(args) -> None:
    from bankintel.ai.client import AiDisabled, build_client
    from bankintel.ai.extractor import run_extraction

    settings = get_settings()
    dry_run, client = args.dry_run, None
    if not dry_run:
        try:
            client = build_client(settings)
        except AiDisabled as exc:
            print(f"AI не запущен: {exc}. Выполняю пробный запуск (ничего не отправляется).")
            dry_run = True
    engine = make_engine(settings.database_url)
    try:
        async with make_session_factory(engine)() as session:
            rep = await run_extraction(session, settings, client, dry_run=dry_run, limit=args.limit)
        print(f"{'ПРОБНЫЙ ЗАПУСК (ничего не отправлено)' if rep.dry_run else 'Готово'}: документов рассмотрено {rep.considered}, "
              f"к отправке {rep.to_send} (~{rep.chars} симв.), сохранено {rep.stored}, фактов принято {rep.facts_accepted}, "
              f"отброшено {rep.facts_rejected}, обновлений ЛНР {rep.lnr_updates}")
        for line in rep.skipped + rep.failed:
            print("  -", line)
    finally:
        await engine.dispose()


async def _discover(slug: str) -> None:

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
                raise SystemExit(f"Импорт отклонён: {exc}") from None
            print(f"Импортировано: document_id={doc.id} sha256={doc.sha256[:12]} {doc.size_bytes} байт")
            print("Добавьте источник в config/sources.yaml (mode: manual, status: active), чтобы он не потерялся при seed:")
            print(f"  - bank: {args.bank}\n    key: {args.source_key}\n    url: {args.url}\n    category: {args.category}\n    status: active\n    mode: manual")
    finally:
        await engine.dispose()


async def _import_dir(args) -> None:
    from pathlib import Path

    from sqlalchemy import select

    from bankintel.db.models import Bank
    from bankintel.sources.manual_batch import (
        MANIFEST_NAME,
        ManifestError,
        import_directory,
        load_manifest,
        write_manifest_template,
    )

    directory = Path(args.dir)
    if not await asyncio.to_thread(directory.is_dir):
        raise SystemExit(f"Папка не найдена: {directory}")
    if args.init:
        try:
            path, n = await asyncio.to_thread(write_manifest_template, directory, category=args.category)
        except ManifestError as exc:
            raise SystemExit(str(exc)) from None
        print(f"Создан {path} ({n} файл.). Заполните пропуски (url, category) и запустите импорт без --init.")
        return
    settings = get_settings()
    cfg = next((b for b in load_config(settings.config_dir).banks if b.slug == args.bank), None)
    if cfg is None:
        raise SystemExit(f"Банк {args.bank!r} не найден в config/banks.yaml")
    try:
        manifest = await asyncio.to_thread(load_manifest, Path(args.manifest) if args.manifest else directory / MANIFEST_NAME)
    except ManifestError as exc:
        raise SystemExit(str(exc)) from None
    engine = make_engine(settings.database_url)
    try:
        async with make_session_factory(engine)() as session:
            bank = await session.scalar(select(Bank).where(Bank.slug == args.bank))
            if bank is None:
                raise SystemExit("Банка нет в БД: выполните bankintel seed")
            rep = await import_directory(
                session, bank, directory, manifest, official_hosts=cfg.official_hosts,
                raw_root=settings.raw_storage_dir, dry_run=args.dry_run,
            )
    finally:
        await engine.dispose()
    icons = {"imported": "OK ", "unchanged": "-- ", "rejected": "ERR"}
    for r in rep.results:
        print(f"{icons[r.status]} {r.file}: {r.detail}")
    for name in rep.unlisted:
        print(f"!! {name}: лежит в папке, но не указан в манифесте — пропущен")
    print(f"\n{'ПРОБНЫЙ ЗАПУСК (ничего не записано). ' if args.dry_run else ''}"
          f"принято {rep.imported}, без изменений {sum(r.status == 'unchanged' for r in rep.results)}, отклонено {rep.rejected}")
    if rep.new_sources and not args.dry_run:
        print("\nДобавьте в config/sources.yaml (mode: manual, status: active), чтобы источники не потерялись при seed:")
        for p in rep.new_sources:
            print(f"  - bank: {args.bank}\n    key: {p.source_key}\n    url: {p.url}\n    category: {p.category}\n    status: active\n    mode: manual")
    if rep.rejected:
        raise SystemExit(1)


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
    idr = sub.add_parser("import-dir", help="пакетный ручной импорт: папка сохранённых страниц + manifest.yaml")
    idr.add_argument("--bank", help="slug банка (обязателен, кроме --init)")
    idr.add_argument("--dir", required=True, help="папка с сохранёнными .html/.pdf")
    idr.add_argument("--manifest", help="путь к манифесту (по умолчанию <dir>/manifest.yaml)")
    idr.add_argument("--init", action="store_true", help="создать шаблон манифеста по файлам папки")
    idr.add_argument("--category", choices=["deposit", "savings", "promo"], help="категория по умолчанию для шаблона (--init)")
    idr.add_argument("--dry-run", action="store_true", help="только проверить, ничего не записывать")
    rp = sub.add_parser("report", help="сформировать отчёты PDF/HTML/PPTX/XLSX из единого набора данных")
    rp.add_argument("--out", default="reports", help="каталог для файлов (по умолчанию ./reports)")
    sub.add_parser("monitor", help="один цикл мониторинга: сбор, страницы продуктов, поиск изменений, уведомления")
    ch = sub.add_parser("changes", help="показать изменения за период")
    ch.add_argument("--days", type=int, default=7)
    pr = sub.add_parser("prune", help="очистка старых снимков/документов (по умолчанию только план)")
    pr.add_argument("--apply", action="store_true", help="выполнить удаление")
    pr.add_argument("--keep-snapshots", type=int, default=20, help="сколько последних снимков хранить на продукт и источник (≥3)")
    pr.add_argument("--attempts-days", type=int, default=90, help="хранить попытки загрузки столько дней")
    pr.add_argument("--documents-days", type=int, default=180, help="не удалять документы моложе стольких дней")
    ai = sub.add_parser("ai-extract", help="AI-извлечение условий со страниц продуктов (по умолчанию пробный запуск без отправки)")
    ai.add_argument("--dry-run", action="store_true", help="только посчитать, что было бы отправлено")
    ai.add_argument("--limit", type=int, default=None)
    sub.add_parser("bot", help="запустить Telegram-бота")
    args = parser.parse_args()
    from bankintel.logging_setup import configure_logging

    _s = get_settings()
    configure_logging(_s.log_level, _s.log_json)
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
    elif args.cmd == "import-dir":
        if not args.init and not args.bank:
            parser.error("import-dir: нужен --bank (кроме --init)")
        asyncio.run(_import_dir(args))
    elif args.cmd == "report":
        asyncio.run(_report(args.out))
    elif args.cmd == "monitor":
        _monitor_once()
    elif args.cmd == "changes":
        asyncio.run(_changes(args.days))
    elif args.cmd == "prune":
        asyncio.run(_prune(args))
    elif args.cmd == "ai-extract":
        asyncio.run(_ai_extract(args))
    elif args.cmd == "bot":
        from bankintel.bot.app import main as bot_main

        bot_main()


if __name__ == "__main__":
    main()
