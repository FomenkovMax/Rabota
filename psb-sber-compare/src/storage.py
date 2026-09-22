"""Хранилище снимков и истории изменений (SQLite).

Почему SQLite: история за календарный год — это десятки тысяч строк, для
такого объёма отдельная СУБД избыточна, а файл БД можно просто положить
рядом с проектом или в сетевую папку. Никаких зависимостей сверх stdlib.

Модель данных:
  runs       — один запуск сбора (дата, регион, сколько собрано)
  products   — условия продукта на момент запуска (снимок)
  promos     — акции на момент запуска
  changes    — зафиксированные отличия от прошлого запуска
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    region        TEXT NOT NULL,
    products_psb  INTEGER DEFAULT 0,
    products_sber INTEGER DEFAULT 0,
    promos        INTEGER DEFAULT 0,
    status        TEXT DEFAULT 'running',
    note          TEXT
);

CREATE TABLE IF NOT EXISTS products (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    bank         TEXT NOT NULL,
    product_key  TEXT NOT NULL,
    title        TEXT NOT NULL,
    category     TEXT,
    region       TEXT,
    rate_min     REAL, rate_max REAL, rate_raw TEXT, rate_conditions TEXT,
    apr_min      REAL, apr_max  REAL, apr_raw  TEXT,
    amount_min   REAL, amount_max REAL, amount_raw TEXT,
    term_min_months INTEGER, term_max_months INTEGER, term_raw TEXT,
    terms_json   TEXT,
    source_url   TEXT,
    fingerprint  TEXT,
    collected_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_products_run  ON products(run_id);
CREATE INDEX IF NOT EXISTS ix_products_key  ON products(bank, product_key);

CREATE TABLE IF NOT EXISTS promos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    bank       TEXT NOT NULL,
    promo_key  TEXT NOT NULL,
    title      TEXT NOT NULL,
    text       TEXT,
    url        TEXT,
    source_path TEXT,
    category   TEXT,
    segment    TEXT,
    status     TEXT,
    valid_until TEXT,
    benefit_type TEXT,
    benefit_value REAL
);
CREATE INDEX IF NOT EXISTS ix_promos_run ON promos(run_id);
CREATE INDEX IF NOT EXISTS ix_promos_key ON promos(bank, promo_key);

CREATE TABLE IF NOT EXISTS changes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    detected_at TEXT NOT NULL,
    bank        TEXT NOT NULL,
    kind        TEXT NOT NULL,     -- rate | promo_new | promo_gone | product_new | product_gone | terms
    product_key TEXT,
    title       TEXT,
    field       TEXT,
    old_value   TEXT,
    new_value   TEXT,
    delta       REAL,
    severity    TEXT DEFAULT 'info'
);
CREATE INDEX IF NOT EXISTS ix_changes_run ON changes(run_id);
"""


class Storage:
    def __init__(self, db_path: str | Path) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """Добавляет колонки, появившиеся после создания базы."""
        existing = {row["name"] for row in self.conn.execute("PRAGMA table_info(products)")}
        for column, ddl in (("rate_conditions", "TEXT"),):
            if column not in existing:
                self.conn.execute(f"ALTER TABLE products ADD COLUMN {column} {ddl}")
                log.info("База обновлена: products.%s", column)

        existing = {row["name"] for row in self.conn.execute("PRAGMA table_info(promos)")}
        for column, ddl in (("segment", "TEXT"), ("status", "TEXT"),
                            ("valid_until", "TEXT"), ("benefit_type", "TEXT"),
                            ("benefit_value", "REAL")):
            if column not in existing:
                self.conn.execute(f"ALTER TABLE promos ADD COLUMN {column} {ddl}")
                log.info("База обновлена: promos.%s", column)

    # --- запуски ---------------------------------------------------------

    def start_run(self, region: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (started_at, region) VALUES (?, ?)",
            (datetime.now().isoformat(timespec="seconds"), region),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, *, psb: int, sber: int, promos: int,
                   status: str = "ok", note: str = "") -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at=?, products_psb=?, products_sber=?, "
            "promos=?, status=?, note=? WHERE id=?",
            (datetime.now().isoformat(timespec="seconds"), psb, sber, promos,
             status, note, run_id),
        )
        self.conn.commit()

    def previous_run_id(self, before_run_id: int) -> int | None:
        row = self.conn.execute(
            "SELECT id FROM runs WHERE id < ? AND status='ok' ORDER BY id DESC LIMIT 1",
            (before_run_id,),
        ).fetchone()
        return int(row["id"]) if row else None

    def last_successful_run_id(self) -> int | None:
        row = self.conn.execute(
            "SELECT id FROM runs WHERE status='ok' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return int(row["id"]) if row else None

    # --- запись ----------------------------------------------------------

    def save_products(self, run_id: int, products: list[Any]) -> None:
        rows = []
        for p in products:
            rows.append((
                run_id, p.bank, product_key(p), p.title, p.category, p.region,
                p.rate_min, p.rate_max, p.rate_raw, getattr(p, "rate_conditions", ""),
                p.apr_min, p.apr_max, p.apr_raw,
                p.amount_min, p.amount_max, p.amount_raw,
                p.term_min_months, p.term_max_months, p.term_raw,
                json.dumps(p.terms, ensure_ascii=False),
                p.source_url, p.fingerprint(), p.collected_at,
            ))
        self.conn.executemany(
            "INSERT INTO products (run_id, bank, product_key, title, category, region,"
            " rate_min, rate_max, rate_raw, rate_conditions,"
            " apr_min, apr_max, apr_raw,"
            " amount_min, amount_max, amount_raw,"
            " term_min_months, term_max_months, term_raw,"
            " terms_json, source_url, fingerprint, collected_at)"
            " VALUES (" + ",".join("?" * 23) + ")",
            rows,
        )
        self.conn.commit()

    def save_promos(self, run_id: int, bank: str, promos: list[Any],
                    category: str = "", insights: dict[str, Any] | None = None) -> None:
        """Сохраняет акции. `insights` — разбор из promos.classify по ключу."""
        insights = insights or {}
        rows = []
        for pr in promos:
            key = pr.key()
            info = insights.get(key)
            rows.append((
                run_id, bank, key, pr.title, pr.text, pr.url, pr.source_path,
                category or getattr(pr, "segment", ""),
                getattr(info, "segment", "") if info else "",
                getattr(info, "status", "") if info else "",
                info.valid_until.isoformat() if info and info.valid_until else "",
                getattr(info, "benefit_type", "") if info else "",
                getattr(info, "benefit_value", None) if info else None,
            ))
        self.conn.executemany(
            "INSERT INTO promos (run_id, bank, promo_key, title, text, url,"
            " source_path, category, segment, status, valid_until,"
            " benefit_type, benefit_value) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        self.conn.commit()

    def save_changes(self, run_id: int, changes: list[dict[str, Any]]) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        rows = [
            (run_id, now, c["bank"], c["kind"], c.get("product_key"), c.get("title"),
             c.get("field"), c.get("old_value"), c.get("new_value"),
             c.get("delta"), c.get("severity", "info"))
            for c in changes
        ]
        self.conn.executemany(
            "INSERT INTO changes (run_id, detected_at, bank, kind, product_key, title,"
            " field, old_value, new_value, delta, severity) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        self.conn.commit()

    # --- чтение ----------------------------------------------------------

    def products_of_run(self, run_id: int, bank: str | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM products WHERE run_id=?"
        args: list[Any] = [run_id]
        if bank:
            sql += " AND bank=?"
            args.append(bank)
        return self.conn.execute(sql, args).fetchall()

    def promos_of_run(self, run_id: int, bank: str | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM promos WHERE run_id=?"
        args: list[Any] = [run_id]
        if bank:
            sql += " AND bank=?"
            args.append(bank)
        return self.conn.execute(sql, args).fetchall()

    def changes_of_run(self, run_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM changes WHERE run_id=? ORDER BY "
            "CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, id",
            (run_id,),
        ).fetchall()

    def rate_history(self, bank: str, product_key: str, days: int = 365) -> list[sqlite3.Row]:
        """Ставка продукта по неделям — для спарклайна в отчёте."""
        since = (date.today() - timedelta(days=days)).isoformat()
        return self.conn.execute(
            "SELECT r.started_at, p.rate_min, p.rate_max FROM products p"
            " JOIN runs r ON r.id = p.run_id"
            " WHERE p.bank=? AND p.product_key=? AND r.started_at >= ? AND r.status='ok'"
            " ORDER BY r.started_at",
            (bank, product_key, since),
        ).fetchall()

    def run_summary(self, limit: int = 60) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM runs WHERE status='ok' ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()

    # --- обслуживание ----------------------------------------------------

    def purge_older_than(self, days: int = 365) -> int:
        """Глубина истории — один календарный год, как договаривались."""
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        cur = self.conn.execute("DELETE FROM runs WHERE started_at < ?", (cutoff,))
        self.conn.commit()
        removed = cur.rowcount or 0
        if removed:
            self.conn.execute("VACUUM")
            log.info("Удалено запусков старше %s дней: %s", days, removed)
        return removed

    def close(self) -> None:
        self.conn.close()


def product_key(product: Any) -> str:
    """Стабильный идентификатор продукта между запусками.

    Для ПСБ это путь страницы — он переживает переименование продукта.
    Для Сбера ключ приходит из выгрузки.
    """
    explicit = getattr(product, "product_key", "")
    if explicit:
        return str(explicit)
    path = getattr(product, "url_path", "")
    return path or getattr(product, "title", "")


@contextmanager
def open_storage(db_path: str | Path) -> Iterator[Storage]:
    store = Storage(db_path)
    try:
        yield store
    finally:
        store.close()
