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


def main() -> None:
    parser = argparse.ArgumentParser(prog="bankintel")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed", help="загрузить реестр банков и источников из config/ в БД")
    sub.add_parser("bot", help="запустить Telegram-бота")
    args = parser.parse_args()
    if args.cmd == "seed":
        asyncio.run(_seed())
    elif args.cmd == "bot":
        from bankintel.bot.app import main as bot_main

        bot_main()


if __name__ == "__main__":
    main()
