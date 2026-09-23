"""Build the DuckDB warehouse from the Parquet staging layer.

The build writes to <warehouse>.tmp and atomically replaces the live file, so a dashboard holding the
old file keeps working until the swap (on Windows the swap fails while the file is open; the error says so).
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path

from edgar_fundamentals import config, db
from edgar_fundamentals.ingest.load import FILES
from edgar_fundamentals.log import get_logger
from edgar_fundamentals.warehouse import aliases

log = get_logger("edgar.warehouse")

TABLES_TO_LOG = [
    "raw_sub", "raw_tag", "raw_pre", "dim_filing", "dim_company", "dim_period", "dim_tag",
    "fact_financial_facts", "restatements", "filing_currency", "fact_normalized",
]


def sql_params() -> dict:
    pq = config.path("parquet_dir")
    params = {f"pq_{n}": db.sql_path_literal(pq / "*" / f"{n}.parquet") for n in FILES}
    params["in_scope_forms"] = ", ".join("'" + f + "'" for f in config.in_scope_forms())
    tol = config.load_yaml("quality_rules.yaml")["tolerances"]
    params["restatement_rel"] = str(tol["restatement_rel"])
    return params


def build(target: Path | None = None) -> dict:
    target = target or config.path("warehouse")
    tmp = target.with_suffix(".duckdb.tmp")
    for p in (tmp, tmp.with_suffix(".tmp.wal")):
        if p.exists():
            p.unlink()
    t_start = time.perf_counter()
    con = db.connect(tmp)
    timings: dict[str, float] = {}
    try:
        aliases.create_alias_table(con)
        aliases.create_sic_table(con)
        params = sql_params()
        for sql_file in sorted(config.SQL_DIR.glob("*.sql")):
            t0 = time.perf_counter()
            db.run_sql_file(con, sql_file, params)
            timings[sql_file.stem] = time.perf_counter() - t0
            log.info("%s: %.1fs", sql_file.name, timings[sql_file.stem])
        t0 = time.perf_counter()
        derived = aliases.apply_derivations(con)
        timings["derivations"] = time.perf_counter() - t0
        log.info("derivations: %s (%.1fs)", derived, timings["derivations"])

        con.execute("CREATE OR REPLACE TABLE build_log (table_name VARCHAR, row_count BIGINT, built_at TIMESTAMP)")
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        counts = {}
        for t in TABLES_TO_LOG:
            counts[t] = db.row_count(con, t)
            con.execute("INSERT INTO build_log VALUES (?, ?, ?)", [t, counts[t], now])
        con.execute("CREATE OR REPLACE TABLE build_meta AS SELECT ? AS built_at, ? AS build_seconds",
                    [now, time.perf_counter() - t_start])
        con.execute("CHECKPOINT")
    finally:
        con.close()

    try:
        os.replace(tmp, target)
    except PermissionError as exc:
        raise PermissionError(
            f"Cannot replace {target}: it is open in another process (the dashboard?). Close it and rerun build."
        ) from exc
    total = time.perf_counter() - t_start
    log.info("warehouse built in %.1fs -> %s (%.1f MB)", total, target, target.stat().st_size / 1e6)
    for t, n in counts.items():
        log.info("  %-24s %12s rows", t, f"{n:,}")
    return {"seconds": total, "timings": timings, "row_counts": counts, "derived_rows": derived,
            "size_bytes": target.stat().st_size}
