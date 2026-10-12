"""CLI:  python -m radar run --hours 24 --dry-run   |   python -m radar bot"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging

from .config import get_env, setup_logging
from .db import DB

log = logging.getLogger("radar")


async def _run(args) -> None:
    from .pipeline import run_once
    db = DB(get_env().data_path / "radar.db")
    res = await run_once(db, hours=args.hours, dry_run=args.dry_run, limit_channels=args.limit_channels)
    print("\n" + "=" * 60 + "\nДАЙДЖЕСТ (HTML, символов: %d)\n" % len(res.digest) + "=" * 60)
    print(res.digest)
    print("=" * 60)
    if res.channel_errors:
        print("Каналы с ошибками:")
        for k, v in res.channel_errors.items():
            print(f"  {k}: {v}")
    if args.dump:
        with open(args.dump, "w", encoding="utf-8") as f:
            json.dump(res.events, f, ensure_ascii=False, indent=2)
        print("События сохранены в", args.dump)


def main() -> None:
    p = argparse.ArgumentParser(prog="radar")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="один запуск пайплайна")
    r.add_argument("--hours", type=float, help="окно в часах (иначе — с прошлого запуска)")
    r.add_argument("--dry-run", action="store_true", help="не писать в БД и не слать в Telegram")
    r.add_argument("--limit-channels", type=int, help="ограничить число каналов (для отладки)")
    r.add_argument("--dump", help="сохранить события в JSON-файл")
    sub.add_parser("bot", help="запустить бота + планировщик")
    args = p.parse_args()
    setup_logging()
    if args.cmd == "run":
        asyncio.run(_run(args))
    elif args.cmd == "bot":
        from .bot.app import run_bot
        asyncio.run(run_bot())


if __name__ == "__main__":
    main()
