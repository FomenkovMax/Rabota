#!/usr/bin/env python3
"""Точка входа инструмента сравнения розничных продуктов.

Команды:
    python run.py collect              сбор по всем включённым банкам
    python run.py collect --bank psb   сбор по одному банку
    python run.py check-bank psb       проверить, берутся ли данные банка
    python run.py banks                список банков и способов сбора
    python run.py report               пересобрать отчёт без похода на сайты
    python run.py export --fmt all     выгрузить свод: xlsx, pdf, html
    python run.py suggest              черновые пары продуктов
    python run.py history              история запусков
    python run.py bot                  запустить Telegram-бота
"""

from __future__ import annotations

import argparse
import logging
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.banks import registry  # noqa: E402
from src.compare import GREEN, GREY, RED, YELLOW  # noqa: E402
from src.pipeline import (Config, collect_bank, load_report_data,  # noqa: E402
                          run as run_all, suggest)
from src.storage import Storage  # noqa: E402


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def cmd_banks(config: Config) -> int:
    enabled = set(config.enabled_banks())
    print(f"{'Код':<10} {'Банк':<12} {'Вкл':<5} {'Пров':<6} Способ сбора")
    print("-" * 82)
    for code in registry.codes():
        cls = registry.get(code)
        print(f"{code:<10} {cls.title:<12} "
              f"{'да' if code in enabled else 'нет':<5} "
              f"{'да' if cls.verified else 'НЕТ':<6} {cls.strategy}")
    print("\nСтолбец «Пров» — подтверждён ли сбор на живых данных.")
    print("Непроверенные банки помечаются в отчёте как неподтверждённые.")
    return 0


def cmd_check_bank(config: Config, code: str) -> int:
    cls = registry.get(code)
    if cls is None:
        print(f"Неизвестный банк «{code}». Доступны: {', '.join(registry.codes())}")
        return 1

    print(f"Банк     : {cls.title}")
    print(f"Способ   : {cls.strategy}")
    if getattr(cls, "protection", ""):
        print(f"Защита   : {cls.protection}")
    print("\nПробую собрать…\n")

    result = collect_bank(config, code)
    if not result.ok:
        print(f"[НЕ ОК] {result.error}")
        print("\nЧто проверить:")
        print("  • установлен ли Playwright: playwright install chromium")
        print("  • установлен ли сертификат НУЦ Минцифры (gosuslugi.ru/crt)")
        print("  • доступен ли сайт с этой машины")
        return 1

    print(f"[ОК] {result.summary}")
    by_category: dict[str, int] = {}
    for product in result.products:
        by_category[product.category] = by_category.get(product.category, 0) + 1
    for category, count in sorted(by_category.items(), key=lambda x: -x[1]):
        print(f"     {count:>3}  {category}")

    print("\nПримеры извлечённых условий:")
    for product in result.products[:6]:
        rate = (f"{product.rate_min:g}–{product.rate_max:g}%"
                if product.rate_min is not None else "ставка не извлечена")
        print(f"     {product.title[:46]:<46} {rate}")

    if not cls.verified:
        print(f"\nСбор прошёл. Если цифры сходятся с сайтом, включи банк в "
              f"config/settings.yaml\nи поставь verified = True в адаптере "
              f"(src/banks/others.py).")
    return 0


def cmd_export(config: Config, fmt: str, open_after: bool) -> int:
    from src.export import build_exports

    data = load_report_data(config)
    if data is None:
        print("Данных нет. Сначала: python run.py collect")
        return 1

    formats = ["xlsx", "pdf", "html"] if fmt == "all" else [fmt]
    files = build_exports(config, data, formats)
    if not files:
        print("Ничего не выгрузилось — смотри лог выше.")
        return 1

    print("Готово:")
    for path in files:
        print(f"  {path}")
    if open_after:
        for path in files:
            if path.suffix == ".html":
                webbrowser.open(path.resolve().as_uri())
    return 0


def cmd_history(config: Config) -> int:
    storage = Storage(config.path("storage", "db_path", default="data/banks.db"))
    runs = storage.run_summary(limit=25)
    if not runs:
        print("Истории пока нет.")
        storage.close()
        return 0
    print(f"{'Дата':<20} {'Продуктов':>10} {'Акций':>7}  Изменений")
    print("-" * 52)
    for row in runs:
        changes = len(storage.changes_of_run(row["id"]))
        print(f"{row['started_at'][:19]:<20} {row['products_psb']:>10} "
              f"{row['promos']:>7}  {changes}")
    storage.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Сравнение розничных продуктов Сбера с конкурентами",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("command", choices=[
        "collect", "check-bank", "banks", "report", "export",
        "suggest", "history", "bot",
    ])
    parser.add_argument("target", nargs="?", default="",
                        help="код банка для check-bank")
    parser.add_argument("--bank", default="", help="собрать только этот банк")
    parser.add_argument("--fmt", default="all",
                        choices=["xlsx", "pdf", "html", "all"])
    parser.add_argument("--config", default=str(ROOT / "config" / "settings.yaml"))
    parser.add_argument("--open", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    setup_logging(args.verbose)

    if args.command == "bot":
        import asyncio

        from bot.main import run as run_bot
        asyncio.run(run_bot())
        return 0

    config = Config.load(args.config)

    if args.command == "banks":
        return cmd_banks(config)
    if args.command == "check-bank":
        code = args.target or args.bank
        if not code:
            print("Укажи банк: python run.py check-bank psb")
            return 1
        return cmd_check_bank(config, code)
    if args.command == "history":
        return cmd_history(config)
    if args.command == "export":
        return cmd_export(config, args.fmt, args.open)
    if args.command == "suggest":
        path = suggest(config, competitor=args.bank)
        print(f"\nЧерновик пар: {path}")
        print("Проверь глазами и перенеси подтверждённые в config/product_map.yaml")
        return 0
    if args.command == "report":
        return cmd_export(config, args.fmt, args.open)

    # collect
    if args.bank:
        result = collect_bank(config, args.bank)
        print(result.summary)
        return 0 if result.ok else 1

    outcome = run_all(config)
    counts = outcome["counts"]
    print("\n" + "=" * 60)
    print(f"Запуск #{outcome['run_id']} завершён")
    print(f"  Банков собрано: {len(outcome['banks'])} — {', '.join(outcome['banks'])}")
    print(f"  Продуктов     : {outcome['products_total']}")
    print(f"  Акций         : {outcome['promos_total']}")
    print(f"  Светофор      : 🔴 {counts[RED]}  🟡 {counts[YELLOW]}  "
          f"🟢 {counts[GREEN]}  ⚪ {counts[GREY]}")
    for failure in outcome["failures"]:
        print(f"  ! {failure}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
