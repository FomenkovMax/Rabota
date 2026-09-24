"""Оркестратор: собрать по банкам → сравнить → сохранить → отчитаться."""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .banks import registry
from .banks.from_file import FileAdapter
from .changes import detect_changes, format_digest
from .compare import Thresholds, build_comparisons, suggest_pairs, summarize
from .promos import EXPIRED, classify_all, compare_segments
from .report import render_report
from .storage import Storage, product_key

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]

#: Наш банк. Все сравнения строятся относительно него.
HOME_BANK = "sber"


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

    def bank_settings(self, code: str) -> dict[str, Any]:
        """Настройки банка: общие плюс личные."""
        common = {
            "region": self.get("region", default="lugansk"),
            "region_label": self.get("region_label", default=""),
            "browser": self.get("browser", default={}) or {},
        }
        common.update(self.get("banks", code, default={}) or {})
        return common

    def enabled_banks(self) -> list[str]:
        banks = self.get("banks", default={}) or {}
        out = [code for code, cfg in banks.items()
               if (cfg or {}).get("enabled", True) and registry.get(code)]
        unknown = [c for c in banks if not registry.get(c)]
        if unknown:
            log.warning("В настройках есть неизвестные банки: %s", ", ".join(unknown))
        return out or list(registry.codes())


def load_pairs(path: str | Path = ROOT / "config" / "product_map.yaml") -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        log.warning("Нет %s — сравнивать нечего", path)
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    pairs = data.get("pairs") or []
    return [p for p in pairs
            if isinstance(p, dict) and (p.get("competitor") or p.get("psb"))]


# --- сбор -----------------------------------------------------------------

def _adapter_for(config: Config, code: str) -> Any:
    """Адаптер банка: с сайта или из файла, если файл задан в настройках."""
    settings = config.bank_settings(code)
    adapter = registry.create(code, region=None, settings=settings)
    source = settings.get("source")
    return FileAdapter(adapter, source) if source else adapter


def collect_bank(config: Config, code: str) -> Any:
    """Собирает один банк и складывает результат в базу."""
    adapter = _adapter_for(config, code)
    log.info("%s: %s", adapter.title, adapter.strategy)

    result = adapter.collect()
    if not result.ok:
        return result

    storage = Storage(config.path("storage", "db_path", default="data/psb_sber.db"))
    try:
        run_id = storage.start_run(config.get("region_label", default=""))
        storage.save_products(run_id, result.products)
        insights = classify_all(result.promos, adapter.title)
        by_title = {i.title: i for i in insights}
        storage.save_promos(
            run_id, adapter.title, result.promos,
            insights={p.key(): by_title[p.title]
                      for p in result.promos if p.title in by_title},
        )
        storage.finish_run(run_id, psb=len(result.products), sber=0,
                           promos=len(result.promos))
    finally:
        storage.close()

    return result


def collect_all(config: Config) -> dict[str, Any]:
    """Обходит все включённые банки. Падение одного не ломает остальные."""
    results: dict[str, Any] = {}
    for code in config.enabled_banks():
        adapter = _adapter_for(config, code)
        log.info("=== %s: %s", adapter.title, adapter.strategy)
        try:
            results[code] = adapter.collect()
        except Exception as exc:                    # noqa: BLE001
            log.exception("%s: сбор упал", adapter.title)
            results[code] = adapter._failed(str(exc))
        log.info("  → %s", results[code].summary)
    return results


# --- история --------------------------------------------------------------

def build_history(storage: Storage, comparisons: list[Any], days: int) -> dict[str, list[tuple[str, float]]]:
    """Средняя витринная ставка по сопоставленным продуктам, по запускам."""
    buckets: dict[str, dict[str, list[float]]] = {}

    for comparison in comparisons:
        for product in (comparison.psb, comparison.sber):
            if product is None:
                continue
            bank = product.bank
            for row in storage.rate_history(bank, product_key(product), days=days):
                if row["rate_min"] is None:
                    continue
                buckets.setdefault(bank, {}).setdefault(
                    row["started_at"], []).append(row["rate_min"])

    series: dict[str, list[tuple[str, float]]] = {}
    for bank, by_date in buckets.items():
        points = [(date, round(statistics.fmean(values), 2))
                  for date, values in sorted(by_date.items())]
        if points:
            series[bank] = points
    return series


# --- данные для отчёта ----------------------------------------------------

def load_report_data(config: Config, *, competitor: str = "") -> dict[str, Any] | None:
    """Собирает всё нужное для отчёта из последнего успешного сбора.

    `competitor` ограничивает сравнение одним банком — так работают кнопки
    «Сравнить Сбер и …». Без него в свод попадают все конкуренты сразу.
    """
    storage = Storage(config.path("storage", "db_path", default="data/psb_sber.db"))
    try:
        run_id = storage.last_successful_run_id()
        if run_id is None:
            return None

        thresholds = Thresholds.from_config(config.get("thresholds"))
        history_days = int(config.get("storage", "history_days", default=365))
        region = config.get("region_label", default="")

        titles = registry.titles()
        home_title = titles.get(HOME_BANK, "Сбер")

        all_products = _rows_to_products(storage.products_of_run(run_id))
        by_bank: dict[str, list[Any]] = {}
        for product in all_products:
            by_bank.setdefault(product.bank, []).append(product)

        sber_products = by_bank.get(home_title, [])
        competitor_codes = [c for c in config.enabled_banks() if c != HOME_BANK]
        if competitor:
            competitor_codes = [competitor]

        comparisons: list[Any] = []
        pairs = load_pairs()
        for code in competitor_codes:
            title = titles.get(code, code)
            comparisons.extend(build_comparisons(
                by_bank.get(title, []), sber_products, pairs, thresholds,
                competitor_code=code,
            ))

        competitor_titles = [titles.get(c, c) for c in competitor_codes]
        promo_rows = storage.promos_of_run(run_id)
        promos_home = classify_all(
            [r for r in promo_rows if r["bank"] == home_title], home_title)
        promos_rival = []
        for title in competitor_titles:
            promos_rival.extend(classify_all(
                [r for r in promo_rows if r["bank"] == title], title))

        active_rival = [p for p in promos_rival if p.status != EXPIRED]
        active_home = [p for p in promos_home if p.status != EXPIRED]
        rival_products = [p for t in competitor_titles for p in by_bank.get(t, [])]

        segments = compare_segments(active_rival, active_home,
                                    psb_products=rival_products,
                                    sber_products=sber_products)

        changes = [dict(row) for row in storage.changes_of_run(run_id)]
        counts = summarize(comparisons)
        history = build_history(storage, comparisons, history_days)

        run_row = storage.conn.execute(
            "SELECT started_at FROM runs WHERE id=?", (run_id,)).fetchone()
        collected_at = (run_row["started_at"][:16].replace("T", " ")
                        if run_row else "")

        # Называем неподтверждённые банки поимённо. Общий флаг «данные не
        # подтверждены» на карточке ЦМР читался как «не подтверждён ЦМР»,
        # хотя не подтверждён был Сбер — и это вводило в заблуждение.
        unverified = []
        for code in competitor_codes + [HOME_BANK]:
            cls = registry.get(code)
            if cls is None:
                continue
            # Банк, который читается из файла, подтверждать нечем и незачем:
            # за содержимое файла отвечает тот, кто его положил.
            if (config.bank_settings(code) or {}).get("source"):
                continue
            if not getattr(cls, "verified", False):
                unverified.append(titles.get(code, code))

        # Сколько продуктов собрано по каждому банку — чтобы отличить
        # «пары не настроены» от «данных по банку вообще нет».
        product_counts = {title: len(items) for title, items in by_bank.items()}

        html = render_report(
            comparisons=comparisons, counts=counts, changes=changes,
            promo_segments=segments, expired_promos=[],
            promo_active_total=len(active_rival) + len(active_home),
            history=history, region=region,
            generated_at=datetime.now().strftime("%d.%m.%Y %H:%M"),
            run_count=len(storage.run_summary(limit=400)),
            psb_total=len(rival_products), sber_total=len(sber_products),
            thresholds=thresholds,
        )

        return {
            "run_id": run_id,
            "region": region,
            "collected_at": collected_at,
            "banks": [home_title] + competitor_titles,
            "comparisons": comparisons,
            "counts": counts,
            "segments": segments,
            "changes": changes,
            "products": all_products,
            "history": history,
            "html": html,
            "unverified": unverified,
            "verified": not unverified,
            "product_counts": product_counts,
            "competitor_titles": competitor_titles,
            "home_title": home_title,
        }
    finally:
        storage.close()


# --- полный прогон --------------------------------------------------------

def run(config: Config) -> dict[str, Any]:
    """Сбор по всем банкам плюс отчёт."""
    storage = Storage(config.path("storage", "db_path", default="data/psb_sber.db"))
    run_id = storage.start_run(config.get("region_label", default=""))

    products_total = promos_total = 0
    banks_ok: list[str] = []
    failures: list[str] = []

    try:
        for code, result in collect_all(config).items():
            if not result.ok:
                failures.append(result.summary)
                continue
            banks_ok.append(result.bank)
            storage.save_products(run_id, result.products)

            insights = classify_all(result.promos, result.bank)
            by_title = {i.title: i for i in insights}
            storage.save_promos(
                run_id, result.bank, result.promos,
                insights={p.key(): by_title[p.title]
                          for p in result.promos if p.title in by_title},
            )
            products_total += len(result.products)
            promos_total += len(result.promos)

        previous = storage.previous_run_id(run_id)
        changes = detect_changes(storage, run_id, previous)
        storage.save_changes(run_id, changes)
        storage.finish_run(run_id, psb=products_total, sber=0,
                           promos=promos_total,
                           note="; ".join(failures) if failures else "")
        storage.purge_older_than(int(config.get("storage", "history_days", default=365)))
    except Exception as exc:
        storage.finish_run(run_id, psb=0, sber=0, promos=0,
                           status="failed", note=str(exc))
        storage.close()
        raise
    storage.close()

    data = load_report_data(config)
    counts = data["counts"] if data else {"red": 0, "yellow": 0, "green": 0, "grey": 0}

    digest_path = config.path("notify", "digest_file", default="data/changes_digest.txt")
    digest_path.parent.mkdir(parents=True, exist_ok=True)
    digest_path.write_text(format_digest(changes), encoding="utf-8")

    return {
        "run_id": run_id,
        "banks": banks_ok,
        "failures": failures,
        "products_total": products_total,
        "promos_total": promos_total,
        "counts": counts,
        "changes": changes,
        "data": data,
    }


def suggest(config: Config, *, competitor: str = "") -> Path:
    """Черновые пары для ручной проверки."""
    storage = Storage(config.path("storage", "db_path", default="data/psb_sber.db"))
    try:
        run_id = storage.last_successful_run_id()
        if run_id is None:
            raise RuntimeError("Нет ни одного сбора. Сначала: python run.py collect")
        products = _rows_to_products(storage.products_of_run(run_id))
    finally:
        storage.close()

    titles = registry.titles()
    home_title = titles.get(HOME_BANK, "Сбер")
    sber_products = [p for p in products if p.bank == home_title]

    codes = [competitor] if competitor else [
        c for c in config.enabled_banks() if c != HOME_BANK]

    lines = [
        "# ЧЕРНОВИК. Проверь каждую пару глазами и перенеси подтверждённые",
        "# в config/product_map.yaml. Этот файл в отчёт НЕ попадает.",
        "",
        "pairs:",
    ]
    for code in codes:
        title = titles.get(code, code)
        rival = [p for p in products if p.bank == title]
        if not rival:
            lines.append(f"  # {title}: продуктов в последнем сборе нет")
            continue
        lines.append(f"  # --- {title} ---")
        for item in suggest_pairs(rival, sber_products):
            best = item["candidates"][0]
            lines.append(f"  # похожесть {best['score']}")
            lines.append(f"  - bank: {code}")
            lines.append(f"    competitor: {item['psb_key']}")
            lines.append(f"    sber: {best['sber_key']}")
            lines.append(f"    label: {item['psb_title']}")
            lines.append(f"    category: {item['category']}")
            lines.append("")

    out = ROOT / "data" / "pairs_suggested.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    log.info("Черновик пар: %s", out)
    return out


def _rows_to_products(rows: list[Any]) -> list[Any]:
    """Строки БД → объекты Product."""
    import json as _json

    from .psb.parser import Product

    out = []
    for row in rows:
        product = Product(
            bank=row["bank"], url_path=row["product_key"], title=row["title"],
            category=row["category"] or "", region=row["region"] or "",
            rate_min=row["rate_min"], rate_max=row["rate_max"],
            rate_raw=row["rate_raw"] or "",
            apr_min=row["apr_min"], apr_max=row["apr_max"],
            apr_raw=row["apr_raw"] or "",
            amount_min=row["amount_min"], amount_max=row["amount_max"],
            amount_raw=row["amount_raw"] or "",
            term_min_months=row["term_min_months"],
            term_max_months=row["term_max_months"],
            term_raw=row["term_raw"] or "",
            terms=_json.loads(row["terms_json"] or "{}"),
            source_url=row["source_url"] or "",
            collected_at=row["collected_at"] or "",
        )
        keys = row.keys()
        if "rate_conditions" in keys:
            product.rate_conditions = row["rate_conditions"] or ""
        object.__setattr__(product, "product_key", row["product_key"])
        out.append(product)
    return out
