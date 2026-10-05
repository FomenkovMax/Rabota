"""SQLite-хранилище срезов. Срезы только дописываются: в завершённый запуск писать нельзя."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

from lnrbank.storage.models import COLUMNS, KEYS, RAW_EXTENSIONS

SCHEMA = Path(__file__).with_name("schema.sql")
FINISHED = ("ok", "partial")


class RunClosedError(RuntimeError):
    """Попытка записать данные в уже завершённый запуск."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Storage:
    def __init__(self, db_path: Path, raw_dir: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.raw_dir = raw_dir
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA.read_text(encoding="utf-8"))

    def close(self) -> None:
        self.conn.close()

    # --- запуски и срезы ---

    def start_run(self, mode: str, blocks: list[str], snapshot_date: str | None = None) -> int:
        snap = snapshot_date or date.today().isoformat()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO runs (snapshot_date, mode, blocks, started_at) VALUES (?, ?, ?, ?)",
                (snap, mode, ",".join(blocks), _now()),
            )
        return cur.lastrowid

    def finish_run(
        self, run_id: int, status: str, summary: dict | None = None, key_rate: float | None = None
    ) -> None:
        self._open_run(run_id)
        with self.conn:
            self.conn.execute(
                "UPDATE runs SET status = ?, finished_at = ?, summary_json = ?, key_rate = ?"
                " WHERE run_id = ?",
                (status, _now(), json.dumps(summary or {}, ensure_ascii=False), key_rate, run_id),
            )

    def _open_run(self, run_id: int) -> str:
        row = self.conn.execute(
            "SELECT snapshot_date, status FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Нет запуска {run_id}")
        if row["status"] != "running":
            raise RunClosedError(f"Запуск {run_id} уже завершён ({row['status']})")
        return row["snapshot_date"]

    def snapshots(self) -> list[str]:
        """Даты срезов с завершёнными запусками, от новых к старым."""
        placeholders = ",".join("?" * len(FINISHED))
        rows = self.conn.execute(
            f"SELECT DISTINCT snapshot_date FROM runs WHERE status IN ({placeholders})"  # noqa: S608
            " ORDER BY snapshot_date DESC",
            FINISHED,
        )
        return [r[0] for r in rows]

    def latest_snapshot(self) -> str | None:
        snaps = self.snapshots()
        return snaps[0] if snaps else None

    def previous_snapshot(self) -> str | None:
        snaps = self.snapshots()
        return snaps[1] if len(snaps) > 1 else None

    # --- данные ---

    def add_rows(self, table: str, run_id: int, rows: list[dict]) -> None:
        if table not in COLUMNS:
            raise ValueError(f"Неизвестная таблица: {table}")
        snap = self._open_run(run_id)
        allowed = COLUMNS[table]
        for row in rows:
            extra = set(row) - set(allowed)
            if extra:
                raise ValueError(f"Неизвестные колонки в {table}: {sorted(extra)}")
        key = KEYS[table]
        where = " AND ".join(f"{k} IS ?" for k in key)
        # Строки прежних запусков того же среза с тем же ключом заменяются новыми.
        delete_sql = f"DELETE FROM {table} WHERE snapshot_date = ? AND run_id != ? AND {where}"  # noqa: S608
        cols = ("run_id", "snapshot_date", *allowed)
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"  # noqa: S608
        with self.conn:
            for row in rows:
                self.conn.execute(delete_sql, (snap, run_id, *(row.get(k) for k in key)))
            self.conn.executemany(
                sql, [(run_id, snap, *(row.get(c) for c in allowed)) for row in rows]
            )

    def rows(self, table: str, snapshot_date: str) -> list[dict]:
        if table not in COLUMNS:
            raise ValueError(f"Неизвестная таблица: {table}")
        cur = self.conn.execute(
            f"SELECT * FROM {table} WHERE snapshot_date = ?",  # noqa: S608
            (snapshot_date,),
        )
        return [dict(r) for r in cur]

    # --- сырые документы ---

    def save_raw_document(
        self, run_id: int, bank: str, url: str, kind: str, content: bytes, region_method: str | None
    ) -> dict:
        if kind not in RAW_EXTENSIONS:
            raise ValueError(f"Неизвестный тип документа: {kind}")
        snap = self._open_run(run_id)
        sha = hashlib.sha256(content).hexdigest()
        # Имя файла — хэш содержимого: путь не зависит от URL, обход каталогов невозможен.
        folder = self.raw_dir / snap / bank
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{sha}.{RAW_EXTENSIONS[kind]}"
        path.write_bytes(content)
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO raw_documents (run_id, snapshot_date, bank, url, kind, path, sha256,"
                " fetched_at, region_method) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, snap, bank, url, kind, str(path), sha, _now(), region_method),
            )
        return {"doc_id": cur.lastrowid, "path": str(path), "sha256": sha}

    def prune_raw(self, keep_snapshots: int) -> int:
        """Удаляет файлы сырых документов старше N срезов. Разобранные данные остаются."""
        old = self.snapshots()[keep_snapshots:]
        removed = 0
        for snap in old:
            docs = self.conn.execute(
                "SELECT doc_id, path FROM raw_documents WHERE snapshot_date = ? AND pruned = 0",
                (snap,),
            ).fetchall()
            for doc in docs:
                Path(doc["path"]).unlink(missing_ok=True)
                removed += 1
            with self.conn:
                self.conn.execute(
                    "UPDATE raw_documents SET pruned = 1 WHERE snapshot_date = ?", (snap,)
                )
        return removed

    # --- кэш LLM ---

    def cache_get(self, content_sha256: str, prompt_version: str, model: str) -> dict | None:
        row = self.conn.execute(
            "SELECT response_json FROM llm_cache"
            " WHERE content_sha256 = ? AND prompt_version = ? AND model = ?",
            (content_sha256, prompt_version, model),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def cache_put(self, content_sha256: str, prompt_version: str, model: str, data: dict) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO llm_cache VALUES (?, ?, ?, ?, ?)",
                (
                    content_sha256,
                    prompt_version,
                    model,
                    json.dumps(data, ensure_ascii=False),
                    _now(),
                ),
            )
