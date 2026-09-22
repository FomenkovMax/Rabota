#!/usr/bin/env python3
"""Точка входа инструмента сравнения ПСБ / Сбер.

Команды:
    python run.py collect        полный прогон: сбор → сравнение → отчёт
    python run.py suggest        черновые пары продуктов для ручной проверки
    python run.py report         пересобрать отчёт без похода на сайт
    python run.py check          проверка доступности сайта и сертификата
    python run.py history        что происходило в прошлых запусках
"""

from __future__ import annotations

import argparse
import logging
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.pipeline import Config, run, suggest  # noqa: E402
from src.storage import Storage  # noqa: E402


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def cmd_check(config: Config) -> int:
    """Проверяет, что до сайта дойти можно и сертификат принят."""
    from src.psb.catalog import build_catalog
    from src.psb.client import REGIONS, PsbClient

    region = REGIONS[config.get("region", default="lugansk")]
    print(f"Регион запроса: {region.city_name} (cityId {region.city_id})")

    try:
        with PsbClient(region=region, pause=0.2) as client:
            html_text = client.get("/personal/loans")
    except RuntimeError as exc:
        print(f"\n[НЕ ОК] {exc}")
        return 1

    print(f"[ОК] Страница получена, {len(html_text):,} символов".replace(",", " "))

    pages = build_catalog(html_text)
    if not pages:
        print("[НЕ ОК] Каталог пуст — структура сайта могла измениться")
        return 1

    print(f"[ОК] Каталог построен: {len(pages)} страниц")
    city = "Луганск" if region.city_id == 811307 else region.city_name
    marker = "[ОК]" if city in html_text else "[ВНИМАНИЕ]"
    print(f"{marker} Регион на странице: {city} "
          f"{'определён' if city in html_text else 'НЕ найден — проверь cookie geoId'}")
    print("\nВсё готово к сбору. Запускай: python run.py collect")
    return 0


def cmd_history(config: Config) -> int:
    storage = Storage(config.path("storage", "db_path", default="data/psb_sber.db"))
    runs = storage.run_summary(limit=25)
    if not runs:
        print("Истории пока нет — ни одного успешного сбора.")
        storage.close()
        return 0

    print(f"{'Дата':<20} {'ПСБ':>5} {'Сбер':>5} {'Акций':>6}  Изменений")
    print("-" * 58)
    for row in runs:
        changes = len(storage.changes_of_run(row["id"]))
        print(f"{row['started_at'][:19]:<20} {row['products_psb']:>5} "
              f"{row['products_sber']:>5} {row['promos']:>6}  {changes}")
    storage.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Сравнение розничных продуктов ПСБ и Сбера",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("command",
                        choices=["collect", "suggest", "report", "check", "history"])
    parser.add_argument("--config", default=str(ROOT / "config" / "settings.yaml"))
    parser.add_argument("--open", action="store_true",
                        help="открыть готовый отчёт в браузере")
    parser.add_argument("--fresh", action="store_true",
                        help="для suggest: обойти сайт заново, а не брать последний сбор")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    setup_logging(args.verbose)
    config = Config.load(args.config)

    if args.command == "check":
        return cmd_check(config)
    if args.command == "history":
        return cmd_history(config)
    if args.command == "suggest":
        path = suggest(config, fresh=args.fresh)
        print(f"\nЧерновик пар записан: {path}")
        print("Проверь его глазами и перенеси подтверждённые пары "
              "в config/product_map.yaml")
        return 0

    result = run(config, skip_collect=(args.command == "report"))

    counts = result["counts"]
    print("\n" + "=" * 58)
    print(f"Запуск #{result['run_id']} завершён")
    print(f"  Продуктов ПСБ : {result['psb']}")
    print(f"  Продуктов Сбер: {result['sber']}")
    print(f"  Акций         : {result['promos']}")
    print(f"  Светофор      : 🔴 {counts['red']}  🟡 {counts['yellow']}  "
          f"🟢 {counts['green']}  ⚪ {counts['grey']}")
    print(f"  Отчёт         : {result['report']}")
    print("=" * 58)
    print("\n" + result["digest"])

    if args.open:
        webbrowser.open(Path(result["report"]).resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
