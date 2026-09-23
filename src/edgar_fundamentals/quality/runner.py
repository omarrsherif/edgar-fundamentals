"""Run every registered rule against the warehouse and persist dq_results / dq_summary."""
from __future__ import annotations

import time
from datetime import datetime, timezone

import duckdb

from edgar_fundamentals import config, db
from edgar_fundamentals.log import get_logger
from edgar_fundamentals.quality.registry import RESULT_COLUMNS, Rule, load_rules, rule_params

log = get_logger("edgar.quality")


def metric_names() -> list[str]:
    return list(config.load_yaml("aliases.yaml")["metrics"].keys())


def prepare(con: duckdb.DuckDBPyConnection) -> None:
    """dq_wide: fact_normalized pivoted to one row per (company, period end, duration) with a
    <metric> value column and a <metric>_status column (reported/derived) for every canonical metric.
    Several rules read from it, so it is built once per run."""
    metrics = metric_names()
    cols = []
    for m in metrics:
        cols.append(f"max(CASE WHEN metric = '{m}' THEN value END) AS {m}")
        cols.append(f"max(CASE WHEN metric = '{m}' THEN status END) AS {m}_status")
    con.execute(f"""
        CREATE OR REPLACE TABLE dq_wide AS
        SELECT cik, period_end, qtrs,
               any_value(fiscal_year) AS fiscal_year, any_value(fiscal_quarter) AS fiscal_quarter,
               arg_max(source_adsh, source_filed) AS adsh,
               any_value(currency) AS currency,
               {", ".join(cols)}
        FROM fact_normalized
        GROUP BY cik, period_end, qtrs
    """)
    con.execute("CREATE OR REPLACE TABLE mandatory_metrics (report_type VARCHAR, metric VARCHAR)")
    mt = config.load_yaml("mandatory_tags.yaml")
    rows = [(rt, m) for rt, ms in mt["forms"].items() for m in ms]
    con.executemany("INSERT INTO mandatory_metrics VALUES (?, ?)", rows)
    con.execute("CREATE OR REPLACE TABLE mandatory_financial_exempt (metric VARCHAR)")
    con.executemany("INSERT INTO mandatory_financial_exempt VALUES (?)", [(m,) for m in mt.get("financial_exempt", [])])
    con.execute("CREATE OR REPLACE TABLE mandatory_conditional (metric VARCHAR, requires_any_of VARCHAR)")
    con.executemany("INSERT INTO mandatory_conditional VALUES (?, ?)",
                    [(m, r) for m, spec in mt.get("conditional", {}).items() for r in spec["requires_any_of"]])


def _projection(con: duckdb.DuckDBPyConnection, table: str) -> str:
    present = {r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()}
    if "status" not in present:
        raise ValueError(f"{table}: rule output lacks a status column")
    parts = []
    for col, typ in RESULT_COLUMNS.items():
        if col in present:
            parts.append(f"CAST({col} AS {typ}) AS {col}")
        elif col == "n":
            parts.append("1::BIGINT AS n")
        else:
            parts.append(f"NULL::{typ} AS {col}")
    return ", ".join(parts)


def run_rule(con: duckdb.DuckDBPyConnection, rule: Rule, params: dict[str, str]) -> dict:
    t0 = time.perf_counter()
    con.execute("DROP TABLE IF EXISTS rule_out")
    con.execute(f"CREATE TEMP TABLE rule_out AS {db.render_sql(rule.sql, params)}")
    proj = _projection(con, "rule_out")
    counts = dict(con.execute(
        f"SELECT status, sum(n) FROM (SELECT {proj} FROM rule_out) GROUP BY status"
    ).fetchall())
    passed = int(counts.get("pass", 0) or 0)
    failed = int(counts.get("fail", 0) or 0)
    skipped = int(counts.get("skip", 0) or 0)
    con.execute(f"""
        INSERT INTO dq_results
        SELECT '{rule.id}' AS rule_id, '{rule.name}' AS rule_name, '{rule.category}' AS category,
               '{rule.severity}' AS severity, {proj}
        FROM rule_out WHERE status = 'fail'
    """)
    seconds = time.perf_counter() - t0
    evaluated = passed + failed
    row = {
        "rule_id": rule.id, "rule_name": rule.name, "category": rule.category, "severity": rule.severity,
        "unit": rule.unit, "description": rule.description,
        "candidates": evaluated + skipped, "evaluated": evaluated, "passed": passed, "failed": failed,
        "skipped": skipped,
        "failure_rate": (failed / evaluated) if evaluated else None,
        "coverage": (evaluated / (evaluated + skipped)) if (evaluated + skipped) else None,
        "seconds": seconds,
    }
    con.execute(
        "INSERT INTO dq_summary VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [row["rule_id"], row["rule_name"], row["category"], row["severity"], row["unit"], row["description"],
         row["candidates"], row["evaluated"], row["passed"], row["failed"], row["skipped"],
         row["failure_rate"], row["coverage"], row["seconds"],
         datetime.now(timezone.utc).replace(tzinfo=None)],
    )
    log.info("%s %-32s pass=%-10s fail=%-9s skip=%-9s rate=%s  (%.1fs)", rule.id, rule.name,
             f"{passed:,}", f"{failed:,}", f"{skipped:,}",
             "n/a" if row["failure_rate"] is None else f"{row['failure_rate']:.4%}", seconds)
    return row


def run_all(con: duckdb.DuckDBPyConnection | None = None, rules: list[Rule] | None = None) -> list[dict]:
    own = con is None
    con = con or db.connect()
    rules = rules or load_rules()
    params = rule_params()
    try:
        prepare(con)
        cols = ", ".join(f"{c} {t}" for c, t in RESULT_COLUMNS.items())
        con.execute("CREATE OR REPLACE TABLE dq_results (rule_id VARCHAR, rule_name VARCHAR, category VARCHAR, "
                    f"severity VARCHAR, {cols})")
        con.execute("CREATE OR REPLACE TABLE dq_summary (rule_id VARCHAR, rule_name VARCHAR, category VARCHAR, "
                    "severity VARCHAR, unit VARCHAR, description VARCHAR, candidates BIGINT, evaluated BIGINT, "
                    "passed BIGINT, failed BIGINT, skipped BIGINT, failure_rate DOUBLE, coverage DOUBLE, "
                    "seconds DOUBLE, run_at TIMESTAMP)")
        out = [run_rule(con, r, params) for r in rules]
        con.execute("DROP TABLE IF EXISTS rule_out")
        return out
    finally:
        if own:
            con.close()
