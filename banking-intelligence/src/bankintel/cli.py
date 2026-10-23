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


async def _collect(include_todo: bool) -> None:
    from bankintel.collector import collect_all
    from bankintel.sources.fetcher import build_fetcher

    settings = get_settings()
    engine = make_engine(settings.database_url)
    fetcher = build_fetcher(settings)
    try:
        async with make_session_factory(engine)() as session:
            for bank, run in await collect_all(session, fetcher, settings.raw_storage_dir, include_todo=include_todo):
                print(f"{bank.slug:8} {run.status:16} {run.message or ''}")
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


def main() -> None:
    parser = argparse.ArgumentParser(prog="bankintel")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed", help="загрузить реестр банков и источников из config/ в БД")
    sub.add_parser("probe", help="проверить доступность корня сайта каждого банка (сохраняет диагностику)")
    sub.add_parser("refresh", help="собрать данные по активным (подтверждённым) источникам")
    d = sub.add_parser("discover", help="найти кандидатов продуктовых страниц на сайте банка")
    d.add_argument("bank")
    sub.add_parser("bot", help="запустить Telegram-бота")
    args = parser.parse_args()
    if args.cmd == "seed":
        asyncio.run(_seed())
    elif args.cmd == "probe":
        asyncio.run(_collect(include_todo=True))
    elif args.cmd == "refresh":
        asyncio.run(_collect(include_todo=False))
    elif args.cmd == "discover":
        asyncio.run(_discover(args.bank))
    elif args.cmd == "bot":
        from bankintel.bot.app import main as bot_main

        bot_main()


if __name__ == "__main__":
    main()
