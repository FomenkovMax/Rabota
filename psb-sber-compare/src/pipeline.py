"""Оркестратор: собрать → сравнить → сохранить → отчитаться."""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .changes import detect_changes, format_digest
from .compare import Thresholds, build_comparisons, suggest_pairs, summarize
from .psb.catalog import RETAIL_SECTIONS, build_catalog
from .psb.client import REGIONS, PageNotFound, PsbClient
from .psb.parser import parse_product
from .report import render_report, write_report
from .sber.loader import load_sber
from .storage import Storage, product_key

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Config:
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: str | Path = ROOT / "config" / "settings.yaml") -> "Config":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls(raw=data)

    def get(self, *keys: str, default: Any = None) -> Any:
        node: Any = self.raw
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def path(self, *keys: str, default: str = "") -> Path:
        value = self.get(*keys, default=default)
        p = Path(value)
        return p if p.is_absolute() else ROOT / p


def load_pairs(path: str | Path = ROOT / "config" / "product_map.yaml") -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        log.warning("Нет %s — сравнивать нечего", path)
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    pairs = data.get("pairs") or []
    return [p for p in pairs if isinstance(p, dict) and p.get("psb")]


# --- сбор -----------------------------------------------------------------

def collect_psb(config: Config) -> tuple[list[Any], list[Any]]:
    """Обходит каталог ПСБ. Возвращает (продукты, акции)."""
    region_key = config.get("region", default="lugansk")
    region = REGIONS.get(region_key)
    if region is None:
        raise ValueError(f"Неизвестный регион «{region_key}». Доступно: {', '.join(REGIONS)}")

    region_label = config.get("region_label", default=region.city_name)
    sections = config.get("psb", "sections", default=[]) or []
    include_promos = bool(config.get("psb", "include_promos", default=True))
    max_pages = int(config.get("psb", "max_pages", default=0) or 0)
    now = datetime.now().isoformat(timespec="seconds")

    client = PsbClient(
        region=region,
        pause=float(config.get("psb", "pause", default=1.0)),
        timeout=int(config.get("psb", "timeout", default=30)),
        retries=int(config.get("psb", "retries", default=3)),
    )

    products: list[Any] = []
    promos: list[Any] = []
    missing = 0

    with client:
        log.info("Строю каталог (регион: %s)…", region.city_name)
        pages = build_catalog(client.get("/personal/loans"), include_promos=include_promos)

        if sections:
            unknown = [s for s in sections if s not in RETAIL_SECTIONS]
            if unknown:
                log.warning("В настройках указаны неизвестные разделы: %s", ", ".join(unknown))
            pages = [p for p in pages if p.section in sections or p.is_promo]

        if max_pages:
            pages = pages[:max_pages]

        log.info("К обходу: %s страниц", len(pages))
        failed = 0

        for index, page in enumerate(pages, 1):
            try:
                html_text = client.get(page.url_path)
            except PageNotFound:
                # Служебный узел дерева CMS без собственной страницы — не сбой.
                missing += 1
                log.debug("Нет страницы: %s", page.url_path)
                continue
            except RuntimeError as exc:
                failed += 1
                log.warning("Пропускаю %s: %s", page.url_path, exc)
                continue

            product = parse_product(html_text, page, region_label, now)
            promos.extend(product.promos)

            # Страница без единого условия — это раздел-лендинг, а не продукт.
            if product.rate_raw or product.amount_raw or len(product.terms) > 1:
                products.append(product)

            if index % 25 == 0:
                log.info("  …%s/%s (продуктов: %s, акций: %s)",
                         index, len(pages), len(products), len(promos))

        if missing:
            log.info("Узлов карты сайта без страницы: %s (это нормально)", missing)
        if failed:
            log.warning("Страниц не удалось загрузить из-за ошибок: %s", failed)

    # Акции дублируются между страницами — схлопываем по тексту.
    unique: dict[str, Any] = {}
    for promo in promos:
        unique.setdefault(promo.key(), promo)

    log.info("Собрано: продуктов %s, уникальных акций %s", len(products), len(unique))
    return products, list(unique.values())


# --- история для графика --------------------------------------------------

def build_history(storage: Storage, comparisons: list[Any], days: int) -> dict[str, list[tuple[str, float]]]:
    """Средняя минимальная ставка по сопоставленным продуктам, по запускам.

    Усреднение — сознательное упрощение: на графике для руководителя нужна
    динамика портфеля целиком, а не 40 линий. Детализация по каждому
    продукту остаётся в таблице и в базе.
    """
    buckets: dict[str, dict[str, list[float]]] = {"ПСБ": {}, "Сбер": {}}

    for comparison in comparisons:
        for bank, product in (("ПСБ", comparison.psb), ("Сбер", comparison.sber)):
            if product is None:
                continue
            for row in storage.rate_history(bank, product_key(product), days=days):
                if row["rate_min"] is None:
                    continue
                buckets[bank].setdefault(row["started_at"], []).append(row["rate_min"])

    series: dict[str, list[tuple[str, float]]] = {}
    for bank, by_date in buckets.items():
        points = [(date, round(statistics.fmean(values), 2))
                  for date, values in sorted(by_date.items())]
        if points:
            series[bank] = points
    return series


# --- основной прогон ------------------------------------------------------

def run(config: Config, *, skip_collect: bool = False) -> dict[str, Any]:
    thresholds = Thresholds.from_config(config.get("thresholds"))
    region_label = config.get("region_label", default="")
    history_days = int(config.get("storage", "history_days", default=365))

    storage = Storage(config.path("storage", "db_path", default="data/psb_sber.db"))
    run_id = storage.start_run(region_label)

    try:
        if skip_collect:
            previous = storage.previous_run_id(run_id)
            if previous is None:
                raise RuntimeError("Нет ни одного прошлого сбора — запусти без --skip-collect")
            log.info("Пропускаю сбор, переиспользую данные запуска #%s", previous)
            psb_products = _rows_to_products(storage.products_of_run(previous, "ПСБ"))
            psb_promos = _rows_to_promos(storage.promos_of_run(previous, "ПСБ"))
        else:
            psb_products, psb_promos = collect_psb(config)

        sber_path = config.path("sber", "source", default="data/sber.xlsx")
        sber_products, sber_promos = load_sber(
            sber_path, region=region_label,
            collected_at=datetime.now().isoformat(timespec="seconds"),
        )

        storage.save_products(run_id, psb_products + sber_products)
        storage.save_promos(run_id, "ПСБ", psb_promos)
        storage.save_promos(run_id, "Сбер", sber_promos)

        previous_run = storage.previous_run_id(run_id)
        changes = detect_changes(storage, run_id, previous_run)
        storage.save_changes(run_id, changes)

        pairs = load_pairs()
        comparisons = build_comparisons(psb_products, sber_products, pairs, thresholds)
        counts = summarize(comparisons)

        history = build_history(storage, comparisons, history_days)

        html_text = render_report(
            comparisons=comparisons,
            counts=counts,
            changes=changes,
            promos_psb=storage.promos_of_run(run_id, "ПСБ"),
            promos_sber=storage.promos_of_run(run_id, "Сбер"),
            history=history,
            region=region_label,
            generated_at=datetime.now().strftime("%d.%m.%Y %H:%M"),
            run_count=len(storage.run_summary(limit=400)),
            psb_total=len(psb_products),
            sber_total=len(sber_products),
            thresholds=thresholds,
        )

        output = config.path("report", "output", default="data/dashboard.html")
        write_report(output, html_text)
        if config.get("report", "keep_dated_copy", default=True):
            dated = output.with_name(f"{output.stem}_{datetime.now():%Y-%m-%d}{output.suffix}")
            write_report(dated, html_text)

        digest = format_digest(changes)
        digest_path = config.path("notify", "digest_file", default="data/changes_digest.txt")
        digest_path.parent.mkdir(parents=True, exist_ok=True)
        digest_path.write_text(digest, encoding="utf-8")

        storage.finish_run(run_id, psb=len(psb_products), sber=len(sber_products),
                           promos=len(psb_promos) + len(sber_promos))
        storage.purge_older_than(history_days)

        return {
            "run_id": run_id,
            "psb": len(psb_products),
            "sber": len(sber_products),
            "promos": len(psb_promos) + len(sber_promos),
            "changes": changes,
            "counts": counts,
            "comparisons": comparisons,
            "report": output,
            "digest": digest,
        }

    except Exception as exc:
        storage.finish_run(run_id, psb=0, sber=0, promos=0, status="failed", note=str(exc))
        raise
    finally:
        storage.close()


def suggest(config: Config) -> Path:
    """Черновые пары для ручной проверки."""
    psb_products, _ = collect_psb(config)
    sber_products, _ = load_sber(config.path("sber", "source", default="data/sber.xlsx"))

    if not sber_products:
        log.warning("Выгрузки Сбера нет — предлагать пары не с чем. "
                    "Сохраню только список продуктов ПСБ.")

    suggestions = suggest_pairs(psb_products, sber_products)
    out = ROOT / "data" / "pairs_suggested.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# ЧЕРНОВИК. Проверь каждую пару глазами и перенеси подтверждённые",
        "# в config/product_map.yaml. Этот файл в отчёт НЕ попадает.",
        "",
        "pairs:",
    ]
    for item in suggestions:
        best = item["candidates"][0]
        lines.append(f"  # похожесть {best['score']}"
                     + (f" | другие варианты: "
                        + ", ".join(c["sber_title"] for c in item["candidates"][1:])
                        if len(item["candidates"]) > 1 else ""))
        lines.append(f"  - psb: {item['psb_key']}")
        lines.append(f"    sber: {best['sber_key']}")
        lines.append(f"    label: {item['psb_title']}")
        lines.append(f"    category: {item['category']}")
        lines.append("")

    if not suggestions:
        lines.append("  # Совпадений выше порога не найдено.")
        lines.append("")
        lines.append("# Продукты ПСБ, доступные для сопоставления:")
        for p in sorted(psb_products, key=lambda x: (x.category, x.title)):
            rate = f"{p.rate_min:.2f}%" if p.rate_min is not None else "ставка не извлечена"
            lines.append(f"#   [{p.category}] {p.title} — {rate} — {p.url_path}")

    out.write_text("\n".join(lines), encoding="utf-8")
    log.info("Черновик пар: %s", out)
    return out


def _rows_to_products(rows: list[Any]) -> list[Any]:
    """Строки БД → объекты Product (для прогона без повторного сбора)."""
    import json as _json

    from .psb.parser import Product

    out = []
    for row in rows:
        product = Product(
            bank=row["bank"], url_path=row["product_key"], title=row["title"],
            category=row["category"] or "", region=row["region"] or "",
            rate_min=row["rate_min"], rate_max=row["rate_max"], rate_raw=row["rate_raw"] or "",
            apr_min=row["apr_min"], apr_max=row["apr_max"], apr_raw=row["apr_raw"] or "",
            amount_min=row["amount_min"], amount_max=row["amount_max"],
            amount_raw=row["amount_raw"] or "",
            term_min_months=row["term_min_months"], term_max_months=row["term_max_months"],
            term_raw=row["term_raw"] or "",
            terms=_json.loads(row["terms_json"] or "{}"),
            source_url=row["source_url"] or "", collected_at=row["collected_at"] or "",
        )
        out.append(product)
    return out


def _rows_to_promos(rows: list[Any]) -> list[Any]:
    from .psb.parser import Promo

    return [
        Promo(title=r["title"], text=r["text"] or "", url=r["url"] or "",
              source_path=r["source_path"] or "")
        for r in rows
    ]
