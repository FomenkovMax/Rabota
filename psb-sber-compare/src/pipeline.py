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
from .banks.base import region_binding
from .banks.from_file import FileAdapter
from . import keyrate, market
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


def collect_bank(config: Config, code: str, *, save: bool = True) -> Any:
    """Собирает один банк и, если просят, складывает результат в базу.

    Проверка банка (`check-bank`) в базу не пишет. Раньше писала — и
    появлялся «успешный сбор», в котором был один банк. Отчёт и бот
    берут последний успешный сбор, поэтому после проверки Сбера они
    показывали только Сбер, а ПСБ как будто исчезал.
    """
    adapter = _adapter_for(config, code)
    log.info("%s: %s", adapter.title, adapter.strategy)

    result = adapter.collect()
    if not result.ok or not save:
        return result

    storage = Storage(config.path("storage", "db_path", default="data/psb_sber.db"))
    try:
        previous = storage.last_successful_run_id()
        run_id = storage.start_run(config.get("region_label", default=""))
        storage.set_key_rate(run_id, keyrate.fetch(config.get("key_rate")))
        _drop_seo(result)
        _mark_region(result)
        storage.save_products(run_id, result.products)
        _keep_unread(storage, result, previous, run_id)
        # Остальные банки берём из прошлого сбора, иначе свод после
        # обновления одного банка показал бы только его.
        if previous is not None:
            moved = storage.carry_over(previous, run_id, except_bank=adapter.title)
            log.info("Остальные банки перенесены из сбора #%s: продуктов %s",
                     previous, moved)
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


#: Сколько дней продукт из прошлых сборов можно переносить, не перечитав.
#: Дольше — цифра слишком старая, честнее показать, что её нет.
KEEP_UNREAD_DAYS = 14


def _keep_unread(storage: Storage, result: Any, previous: int | None, run_id: int) -> None:
    """Обход оборвался — непрочитанные продукты банка берём из прошлого сбора.

    Переносится не всё подряд. Первый перенос 07.10.2026 вернул в отчёт
    вчерашний мусор, разобранный ещё старыми правилами: «Ипотечные
    каникулы 30 %» и копию семейной ипотеки со взносом 20,1 % вместо
    ставки — рядом со свежей страницей той же ипотеки. Поэтому не
    переносятся: продукты с тем же названием, что и свежие (адрес у
    карточки на витрине и у страницы продукта разный), страницы, которые
    нынешние правила продуктом не считают, и всё старше двух недель.
    """
    if previous is None or not getattr(result, "partial", False):
        return
    from datetime import datetime, timedelta

    from .banks.crawl_adapter import is_product_title, normalize_title
    from .banks.seo import is_seo_page

    fresh_keys = {product_key(p) for p in result.products}
    fresh_titles = {normalize_title(p.title) for p in result.products}
    cutoff = (datetime.now() - timedelta(days=KEEP_UNREAD_DAYS)).isoformat()
    keep = []
    for row in storage.products_of_run(previous, result.bank):
        if row["product_key"] in fresh_keys or normalize_title(row["title"]) in fresh_titles:
            continue
        if is_seo_page(row["source_url"] or ""):
            continue
        if not is_product_title(row["title"]) or (row["collected_at"] or "") < cutoff:
            continue
        keep.append(row["id"])
    kept = storage.copy_products(run_id, keep)
    if kept:
        log.warning("%s: обход неполный — %s продуктов взяты из сбора #%s "
                    "со своей датой", result.bank, kept, previous)


def _drop_seo(result: Any) -> None:
    """SEO-копии продуктов («Кредит на айфон») в базу не пишем."""
    from .banks.seo import is_seo_page

    result.products = [p for p in result.products
                       if not is_seo_page(getattr(p, "source_url", ""))]


def _mark_region(result: Any) -> None:
    """Каждому продукту — способ привязки к ЛНР, с которым его собрали."""
    for product in result.products:
        if not getattr(product, "region_method", ""):
            product.region_method = getattr(result, "region_method", "") or "selector"


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

def bank_region_methods(config: Config, codes: list[str] | None = None) -> dict[str, str]:
    """Как условия банка привязаны к ЛНР по текущим настройкам: название → способ.

    Банк из файла сюда не попадает: за его содержимое отвечает тот, кто
    положил файл, и для расчётов он считается привязанным (selector).
    """
    titles = registry.titles()
    out: dict[str, str] = {}
    for code in codes if codes is not None else config.enabled_banks():
        cls = registry.get(code)
        settings = config.bank_settings(code) or {}
        if cls is None or settings.get("source"):
            continue
        method, _ = region_binding(getattr(cls, "sets_region", False), settings)
        out[titles.get(code, code)] = method
    return out


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

        # SEO-страницы отсеиваем и здесь: в базе они остались от прошлых
        # сборов, а пересобирать ради этого все банки незачем.
        from .banks.seo import is_seo_page

        all_products = [p for p in _rows_to_products(storage.products_of_run(run_id))
                        if not is_seo_page(p.source_url)]
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

        # Как привязаны условия банков к ЛНР. «Не выбран» — предупреждение:
        # это условия по адресу сервера. «Единые по РФ» — правило заказчика
        # для сайтов, где про ЛНР ничего нет; такие условия сравниваются.
        region_methods = bank_region_methods(config, competitor_codes + [HOME_BANK])
        no_region = [t for t, m in region_methods.items() if m == "not_confirmed"]
        federal = [t for t, m in region_methods.items() if m == "federal"]

        # Ключевая ставка — та, что действовала на дату сбора.
        key = keyrate.ensure(storage, run_id, run_row["started_at"] if run_row else "",
                             config.get("key_rate"))
        key_rate = key.value if key else None

        scope = [p for t in [home_title] + competitor_titles for p in by_bank.get(t, [])]

        # Витрина в блоке акций — только ставки, прошедшие проверки: иначе
        # «Платинум 5 %» (ставка льготного периода) выигрывал бы сегмент.
        def checked(products: list[Any]) -> list[Any]:
            return [p for p in products if market.assess(
                p, key_rate=key_rate, region_method=region_methods.get(p.bank, ""),
            ).confidence != market.LOW]

        rival_products = [p for t in competitor_titles for p in by_bank.get(t, [])]
        segments = compare_segments(active_rival, active_home,
                                    psb_products=checked(rival_products),
                                    sber_products=checked(sber_products))
        gaps = market.build_gaps(scope, home=home_title, key_rate=key_rate,
                                 region_methods=region_methods,
                                 parity_pp=thresholds.parity)
        quality_rows, manual = market.quality(scope, key_rate=key_rate,
                                              region_methods=region_methods)

        html = render_report(
            comparisons=comparisons, counts=counts, changes=changes,
            promo_segments=segments, expired_promos=[],
            promo_active_total=len(active_rival) + len(active_home),
            history=history, region=region,
            generated_at=datetime.now().strftime("%d.%m.%Y %H:%M") + " МСК",
            run_count=len(storage.run_summary(limit=400)),
            psb_total=len(rival_products), sber_total=len(sber_products),
            thresholds=thresholds,
            catalog={title: by_bank.get(title, [])
                     for title in [home_title] + competitor_titles},
            catalog_banks=[home_title] + competitor_titles,
            key_rate=key.label if key else "",
            gaps=gaps, quality_rows=quality_rows, manual=manual, home=home_title,
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
            "no_region": no_region,
            "federal": federal,
            "verified": not unverified,
            "product_counts": product_counts,
            "competitor_titles": competitor_titles,
            "home_title": home_title,
            "key_rate": key_rate,
            "key_rate_label": key.label if key else "",
            "gaps": gaps,
            "quality": quality_rows,
            "manual": manual,
            "region_methods": region_methods,
            "product_ids": market.product_ids(all_products),
        }
    finally:
        storage.close()


# --- полный прогон --------------------------------------------------------

def run(config: Config) -> dict[str, Any]:
    """Сбор по всем банкам плюс отчёт."""
    storage = Storage(config.path("storage", "db_path", default="data/psb_sber.db"))
    previous_ok = storage.last_successful_run_id()
    run_id = storage.start_run(config.get("region_label", default=""))
    storage.set_key_rate(run_id, keyrate.fetch(config.get("key_rate")))

    products_total = promos_total = 0
    banks_ok: list[str] = []
    failures: list[str] = []

    try:
        for code, result in collect_all(config).items():
            if not result.ok:
                failures.append(result.summary)
                continue
            banks_ok.append(result.bank)
            _drop_seo(result)
            _mark_region(result)
            storage.save_products(run_id, result.products)
            _keep_unread(storage, result, previous_ok, run_id)

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
        if "region_method" in keys:
            product.region_method = row["region_method"] or ""
        object.__setattr__(product, "product_key", row["product_key"])
        out.append(product)
    return out
