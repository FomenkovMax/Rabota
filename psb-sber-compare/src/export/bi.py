"""Выгрузка для BI: плоские таблицы в длинном формате с историей всех срезов.

Одна строка — одно значение, у каждой строки дата среза. Новый срез
просто дописывается к истории, и Power BI, DataLens или Superset строят
динамику без переделки модели.

Файлы каждый раз собираются заново из базы целиком, а не дописываются:
так выгрузка не зависит от того, не потерялся ли прошлый файл, а при
исправлении разбора история пересчитывается одинаково для всех срезов.
Срез — последний успешный сбор дня.

Формат: UTF-8 с BOM (иначе Excel покажет кириллицу кракозябрами; Power BI
и DataLens BOM понимают), разделитель — запятая, десятичный разделитель —
точка, даты ГГГГ-ММ-ДД.
"""

from __future__ import annotations

import csv
import logging
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import market

log = logging.getLogger(__name__)

TABLES: dict[str, list[str]] = {
    "snapshots": ["snapshot_date", "run_id", "key_rate", "key_rate_date",
                  "banks", "products"],
    "banks": ["snapshot_date", "bank", "bank_code", "in_lnr", "presence_format",
              "scope", "region_method", "products"],
    "products": ["snapshot_date", "bank", "bank_code", "product_id", "block",
                 "product_type", "program", "product_name", "available_in_lnr",
                 "region_method", "confidence", "source_url", "notes"],
    "conditions": ["snapshot_date", "bank", "product_id", "parameter", "value", "unit",
                   "condition", "better", "region_method", "source_type", "source_url",
                   "evidence", "confidence", "collected_at"],
    "changes": ["snapshot_date", "prev_snapshot_date", "bank", "product_id", "kind",
                "parameter", "old_value", "new_value", "delta", "alert"],
    "gaps": ["snapshot_date", "block", "program", "metric", "better", "sber_value",
             "sber_product", "rank", "banks_compared", "best_bank", "best_value",
             "best_product", "others_median", "delta_vs_best", "delta_vs_median",
             "status", "comment"],
    "data_quality": ["snapshot_date", "bank", "block", "products", "params_planned",
                     "params_collected", "params_usable", "not_confirmed",
                     "low_confidence", "coverage_pct", "issues"],
}

#: Параметры продукта в длинном формате: колонка модели → имя, единица, сырой текст.
PARAMETERS = (
    ("rate_min", "rate_min", "% годовых", "rate_raw"),
    ("rate_max", "rate_max", "% годовых", "rate_raw"),
    ("apr_min", "psk_min", "% годовых", "apr_raw"),
    ("apr_max", "psk_max", "% годовых", "apr_raw"),
    ("amount_min", "amount_min", "₽", "amount_raw"),
    ("amount_max", "amount_max", "₽", "amount_raw"),
    ("term_min_months", "term_min", "мес", "term_raw"),
    ("term_max_months", "term_max", "мес", "term_raw"),
)


def _better(parameter: str, category: str) -> str:
    if parameter.startswith("rate"):
        return market.better_of(category)
    if parameter.startswith("psk"):
        return "lower"
    if parameter == "amount_max":
        return "higher"
    if parameter == "amount_min":
        return "lower"
    return ""


def _num(value: Any) -> Any:
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return "" if value is None else value


def collect_tables(storage: Any, *, home: str, region_methods: dict[str, str],
                   bank_settings: dict[str, dict[str, Any]] | None = None,
                   parity_pp: float = 0.5,
                   key_rate_settings: dict[str, Any] | None = None,
                   ) -> dict[str, list[dict[str, Any]]]:
    """Все таблицы по всем срезам в базе."""
    from .. import keyrate
    from ..pipeline import _rows_to_products

    bank_settings = bank_settings or {}
    tables: dict[str, list[dict[str, Any]]] = {name: [] for name in TABLES}
    previous_date = ""

    for run in storage.snapshots():
        run_id = run["id"]
        snapshot = run["started_at"][:10]
        key = keyrate.ensure(storage, run_id, run["started_at"], key_rate_settings)
        key_rate = key.value if key else None
        products = _rows_to_products(storage.products_of_run(run_id))
        ids = market.product_ids(products)
        by_key = {getattr(p, "product_key", p.url_path): ids[id(p)] for p in products}

        tables["snapshots"].append({
            "snapshot_date": snapshot, "run_id": run_id, "key_rate": _num(key_rate),
            "key_rate_date": key.on if key else "",
            "banks": len({p.bank for p in products}), "products": len(products),
        })

        counts: dict[str, int] = {}
        methods: dict[str, str] = {}
        for product in products:
            counts[product.bank] = counts.get(product.bank, 0) + 1
            methods.setdefault(product.bank, market.method_of(product, region_methods))
        for bank, count in sorted(counts.items()):
            settings = bank_settings.get(bank, {})
            tables["banks"].append({
                "snapshot_date": snapshot, "bank": bank, "bank_code": market.bank_code(bank),
                "in_lnr": settings.get("in_lnr", "unknown"),
                "presence_format": settings.get("presence_format", ""),
                "scope": "main", "region_method": methods[bank], "products": count,
            })

        for product in products:
            method = market.method_of(product, region_methods)
            check = market.assess(product, key_rate=key_rate, region_method=method)
            pid = ids[id(product)]
            category = product.category or ""
            showcase = bool((product.terms or {}).get("Источник ставки"))
            tables["products"].append({
                "snapshot_date": snapshot, "bank": product.bank,
                "bank_code": market.bank_code(product.bank), "product_id": pid,
                "block": market.block_of(product), "product_type": category,
                "program": market.program_of(product), "product_name": product.title,
                "available_in_lnr": "unknown", "region_method": method,
                "confidence": check.confidence, "source_url": product.source_url,
                "notes": "; ".join(check.issues),
            })
            for column, parameter, unit, raw in PARAMETERS:
                value = getattr(product, column, None)
                if value is None:
                    continue
                confidence = check.confidence
                source_type = "page"
                if parameter.startswith("rate") and showcase:
                    source_type = "showcase"
                tables["conditions"].append({
                    "snapshot_date": snapshot, "bank": product.bank, "product_id": pid,
                    "parameter": parameter, "value": _num(value), "unit": unit,
                    "condition": (getattr(product, "rate_conditions", "")
                                  if parameter.startswith("rate") else ""),
                    "better": _better(parameter, category), "region_method": method,
                    "source_type": source_type, "source_url": product.source_url,
                    "evidence": (getattr(product, raw, "") or "")[:200],
                    "confidence": confidence, "collected_at": product.collected_at,
                })

        for change in storage.changes_of_run(run_id):
            key = change["product_key"] or ""
            tables["changes"].append({
                "snapshot_date": snapshot, "prev_snapshot_date": previous_date,
                "bank": change["bank"], "product_id": by_key.get(key, key),
                "kind": change["kind"], "parameter": change["field"] or "",
                "old_value": change["old_value"] or "", "new_value": change["new_value"] or "",
                "delta": _num(change["delta"]),
                "alert": "yes" if change["severity"] in ("high", "medium") else "no",
            })

        for gap in market.build_gaps(products, home=home, key_rate=key_rate,
                                     region_methods=region_methods, parity_pp=parity_pp):
            tables["gaps"].append({
                "snapshot_date": snapshot, "block": gap.block, "program": gap.program,
                "metric": gap.metric, "better": gap.better,
                "sber_value": _num(gap.sber.value if gap.sber else None),
                "sber_product": gap.sber.title if gap.sber else "",
                "rank": _num(gap.rank), "banks_compared": gap.banks_compared,
                "best_bank": gap.best.bank if gap.best else "",
                "best_value": _num(gap.best.value if gap.best else None),
                "best_product": gap.best.title if gap.best else "",
                "others_median": _num(gap.others_median),
                "delta_vs_best": _num(gap.delta_vs_best),
                "delta_vs_median": _num(gap.delta_vs_median),
                "status": gap.status, "comment": gap.comment,
            })

        rows, _ = market.quality(products, key_rate=key_rate, region_methods=region_methods)
        for row in rows:
            tables["data_quality"].append({
                "snapshot_date": snapshot, "bank": row.bank, "block": row.block,
                "products": row.products, "params_planned": row.rated,
                "params_collected": row.with_rate, "params_usable": row.usable,
                "not_confirmed": row.not_confirmed, "low_confidence": row.low,
                "coverage_pct": _num(row.coverage_pct),
                "issues": "; ".join(f"{k}: {v}" for k, v in row.issues.items()),
            })

        previous_date = snapshot
    return tables


def write(out_dir: str | Path, tables: dict[str, list[dict[str, Any]]]) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, columns in TABLES.items():
        path = out / f"{name}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(tables.get(name, []))
        paths.append(path)
    dictionary = out / "data_dictionary.md"
    dictionary.write_text(DICTIONARY, encoding="utf-8")
    paths.append(dictionary)
    return paths


def build(config: Any, *, out_dir: Path | None = None) -> Path:
    """Пишет bi/*.csv и словарь полей, возвращает архив со всем этим."""
    from ..banks import registry
    from ..pipeline import HOME_BANK, bank_region_methods
    from ..compare import Thresholds
    from ..storage import Storage

    out_dir = out_dir or config.path("export", "bi_dir", default="data/bi")
    titles = registry.titles()
    settings = {titles.get(code, code): config.bank_settings(code)
                for code in registry.codes()}
    storage = Storage(config.path("storage", "db_path", default="data/banks.db"))
    try:
        tables = collect_tables(
            storage, home=titles.get(HOME_BANK, "Сбер"),
            region_methods=bank_region_methods(config, registry.codes()),
            bank_settings=settings,
            parity_pp=Thresholds.from_config(config.get("thresholds")).parity,
            key_rate_settings=config.get("key_rate"))
    finally:
        storage.close()

    paths = write(out_dir, tables)
    export_dir = config.path("export", "dir", default="data/export")
    export_dir.mkdir(parents=True, exist_ok=True)
    archive = export_dir / f"bi_{datetime.now():%Y-%m-%d}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in paths:
            zf.write(path, arcname=f"bi/{path.name}")
    log.info("BI: %s срезов, архив %s", len(tables["snapshots"]), archive)
    return archive


DICTIONARY = """# Справочник полей BI-выгрузки

Все таблицы плоские, в длинном формате, у каждой строки есть `snapshot_date`.
Срез — последний успешный сбор дня. Файлы пересобираются из базы целиком
при каждой выгрузке, поэтому история всегда полная.

Формат: CSV, UTF-8 (с BOM), разделитель — запятая, десятичный разделитель — точка,
даты — ГГГГ-ММ-ДД, время — ГГГГ-ММ-ДДTЧЧ:ММ:СС.

## Связи

- `snapshot_date` — общая ось времени всех таблиц.
- `bank` — название банка; `bank_code` — код (SBER, PSB, VTB, TBANK, ROSTFIN, CMR).
- `product_id` — `{BANK}-{блок}-{короткое имя}`, связывает products, conditions и changes.
  Имя берётся из адреса страницы продукта, поэтому переименование продукта
  историю не рвёт. Если продукт переехал на другой адрес, id изменится.

Коды блоков: DEP — сбережения, CARD — карты, LOAN — кредиты, MTG — ипотека,
DAILY — повседневный банкинг, INV — инвестиции, пенсии, страхование,
SEG — сегментные предложения и акции, OTHER — прочее.

Способ привязки к ЛНР (`region_method`):
- `selector` — регион выбран на сайте банка;
- `local` — банк работает только в ЛНР, условия на сайте и есть луганские;
- `federal` — про ЛНР на сайте ничего нет, действуют единые условия по РФ (правило заказчика);
- `not_confirmed` — регион на сайте выбирается, но не задан: условия не ЛНР.
  Такие значения есть в данных, но не идут в рейтинги и выводы.

Достоверность (`confidence`): `high` — со страницы продукта, проверки пройдены;
`medium` — ставка с витрины раздела или не распознано название;
`low` — не прошла проверку правдоподобия или регион не подтверждён. В gaps не идёт.

## snapshots — срезы

| Поле | Тип | Описание |
|---|---|---|
| snapshot_date | date | дата среза |
| run_id | int | номер сбора в базе |
| key_rate | decimal | ключевая ставка ЦБ, % годовых (cbr.ru) |
| key_rate_date | date | на какую дату ставка |
| banks | int | банков в срезе |
| products | int | продуктов в срезе |

## banks — банки

| Поле | Тип | Описание |
|---|---|---|
| in_lnr | text | yes / no / unknown — работает ли банк в ЛНР (из настроек; по умолчанию unknown) |
| presence_format | text | формат присутствия, если задан в настройках |
| scope | text | main — основной список |
| region_method | text | см. выше |
| products | int | продуктов банка в срезе |

## products — продуктовые линейки

| Поле | Тип | Описание |
|---|---|---|
| product_id | text | стабильный id |
| block | text | код блока |
| product_type | text | категория на сайте банка |
| program | text | программа для сравнения (семейная ипотека, автокредит…) |
| product_name | text | название на сайте |
| available_in_lnr | text | yes / no / unknown; пока всегда unknown — проверка доступности отдельный этап |
| region_method | text | см. выше |
| confidence | text | high / medium / low |
| source_url | text | страница-источник |
| notes | text | замечания проверок |

## conditions — условия, одна строка — один параметр

| Поле | Тип | Описание |
|---|---|---|
| parameter | text | rate_min, rate_max, psk_min, psk_max, amount_min, amount_max, term_min, term_max |
| value | decimal | значение |
| unit | text | % годовых / ₽ / мес |
| condition | text | условия лучшей ставки, если банк их указал |
| better | text | higher / lower — что выгоднее клиенту |
| source_type | text | page — страница продукта; showcase — карточка на витрине раздела |
| evidence | text | исходный текст со страницы, до 200 символов |
| confidence | text | high / medium / low |
| collected_at | datetime | когда собрано |

Диапазон «от … до …» — два параметра (_min и _max). Если банк указал одну цифру,
_min и _max совпадают.

## changes — изменения к прошлому срезу

| Поле | Тип | Описание |
|---|---|---|
| prev_snapshot_date | date | с каким срезом сравнивали |
| kind | text | rate, terms, product_new, product_gone, promo_new, promo_gone |
| parameter | text | что изменилось |
| old_value, new_value | text | было и стало |
| delta | decimal | разница ставки, п.п. |
| alert | text | yes — ставка сдвинулась на 0,25 п.п. и больше, продукт или акция появились или ушли |

## gaps — место Сбера

| Поле | Тип | Описание |
|---|---|---|
| block, program | text | блок и программа |
| metric | text | rate_max для вкладов и счетов, rate_min для кредитов |
| better | text | higher / lower |
| sber_value, sber_product | decimal, text | лучшая ставка Сбера в программе и продукт |
| rank | int | место Сбера (1 — лучший) |
| banks_compared | int | сколько банков с проверенной ставкой |
| best_bank, best_value, best_product | text, decimal, text | лучший на рынке |
| others_median | decimal | медиана остальных банков (без Сбера) |
| delta_vs_best | decimal | Сбер − лучший, п.п. |
| delta_vs_median | decimal | Сбер − медиана, п.п. |
| status | text | лидер / в рынке / отстаёт / не найдено у Сбера / нет у конкурентов / нет данных |
| comment | text | пояснение |

«В рынке» — отклонение от медианы остальных не больше порога паритета
(thresholds.parity_pp, по умолчанию 0,5 п.п.).

## data_quality — качество данных

| Поле | Тип | Описание |
|---|---|---|
| products | int | продуктов банка в блоке |
| params_planned | int | продуктов, у которых ключевой параметр — ставка |
| params_collected | int | из них ставка найдена |
| params_usable | int | из них ставка прошла проверки |
| not_confirmed | int | продуктов с неподтверждённым регионом |
| low_confidence | int | продуктов с низкой достоверностью |
| coverage_pct | decimal | params_usable / params_planned, %; пусто — у блока ставок нет |
| issues | text | замечания и их число |
"""
