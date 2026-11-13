"""Merge one completed bank snapshot without replacing newer rival snapshots.

The caller must stop collectors first. This operation refuses unfinished runs,
checks the destination head under a write lock, and preserves stored evidence
and collection timestamps byte-for-byte. A successful crawl can still be partial;
the source note is retained rather than claiming complete coverage.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sqlite3


def merge_bank(destination: Path, source: Path, *, bank: str,
               source_run: int, expected_main_run: int, after_source_run: int) -> int:
    destination, source = destination.resolve(), source.resolve()
    if destination == source or not destination.is_file() or not source.is_file():
        raise ValueError("Two existing, different databases are required")
    if source_run <= after_source_run:
        raise ValueError("Source run predates the isolated collection")
    conn = sqlite3.connect(destination.as_uri() + "?mode=rw", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("ATTACH DATABASE ? AS incoming", (source.as_uri() + "?mode=ro",))
        conn.execute("BEGIN IMMEDIATE")
        main = conn.execute("SELECT * FROM runs WHERE status='ok' ORDER BY id DESC LIMIT 1").fetchone()
        collected = conn.execute("SELECT * FROM incoming.runs WHERE id=?", (source_run,)).fetchone()
        if main is None or main["id"] != expected_main_run:
            raise ValueError("Destination changed; inspect its latest snapshot before merging")
        if conn.execute("SELECT 1 FROM runs WHERE status='running' LIMIT 1").fetchone():
            raise ValueError("Destination has an unfinished collection")
        if collected is None or collected["status"] != "ok" or not collected["finished_at"]:
            raise ValueError("Source collection has not completed successfully")
        if main["region"] != collected["region"]:
            raise ValueError("Snapshot regions do not match")
        if not conn.execute("SELECT 1 FROM incoming.products WHERE run_id=? AND bank=? LIMIT 1",
                            (source_run, bank)).fetchone():
            raise ValueError("Source bank snapshot is empty")
        # A copied baseline is not evidence that the isolated bank actually ran.
        baseline = conn.execute("SELECT finished_at FROM incoming.runs WHERE id=?",
                                (after_source_run,)).fetchone()
        if baseline is None or not baseline["finished_at"]:
            raise ValueError("Source baseline is missing or unfinished")
        fresh = conn.execute(
            "SELECT 1 FROM incoming.products WHERE run_id=? AND bank=? AND collected_at>? LIMIT 1",
            (source_run, bank, baseline["finished_at"])).fetchone()
        if not fresh:
            raise ValueError("Source contains no products collected during this run")
        now = datetime.now().isoformat(timespec="seconds")
        note = (f"Merged {bank} from {source.name} run {source_run}; "
                f"other banks from run {expected_main_run}. Source: {collected['note'] or ''}")
        new_run = conn.execute(
            "INSERT INTO runs (started_at,region,key_rate,key_rate_date,note) VALUES (?,?,?,?,?)",
            (now, main["region"], main["key_rate"], main["key_rate_date"], note)).lastrowid
        for table in ("products", "promos", "coverage"):
            columns = [r["name"] for r in conn.execute(f"PRAGMA main.table_info({table})")
                       if r["name"] not in ("id", "run_id")]
            source_columns = [r["name"] for r in conn.execute(f"PRAGMA incoming.table_info({table})")
                              if r["name"] not in ("id", "run_id")]
            if columns != source_columns:
                raise ValueError(f"Incompatible schema: {table}")
            names = ",".join('"' + c + '"' for c in columns)
            conn.execute(f"INSERT INTO {table} (run_id,{names}) SELECT ?,{names} FROM main.{table} "
                         "WHERE run_id=? AND bank!=?", (new_run, expected_main_run, bank))
            conn.execute(f"INSERT INTO {table} (run_id,{names}) SELECT ?,{names} FROM incoming.{table} "
                         "WHERE run_id=? AND bank=?", (new_run, source_run, bank))
        counts = dict(conn.execute("SELECT bank,count(*) FROM products WHERE run_id=? GROUP BY bank", (new_run,)))
        promos = conn.execute("SELECT count(*) FROM promos WHERE run_id=?", (new_run,)).fetchone()[0]
        conn.execute("UPDATE runs SET finished_at=?,status='ok',products_psb=?,products_sber=?,promos=? WHERE id=?",
                     (now, counts.get("ПСБ", 0), counts.get("Сбер", 0), promos, new_run))
        conn.commit()
        return int(new_run)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("source", type=Path)
    parser.add_argument("--bank", required=True)
    parser.add_argument("--source-run", type=int, required=True)
    parser.add_argument("--expected-main-run", type=int, required=True)
    parser.add_argument("--after-source-run", type=int, required=True)
    args = vars(parser.parse_args())
    print(merge_bank(**args))
