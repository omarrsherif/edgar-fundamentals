"""Save EXPLAIN ANALYZE plans for the five dashboard queries (cold and warm) and reproduce the
company_search first-statement bisection.

cold plan = EXPLAIN ANALYZE issued as the FIRST statement of a fresh Python process on a fresh
           read-only connection (the same definition of "cold" the benchmark uses)
warm plan = EXPLAIN ANALYZE after 5 plain executions of the same statement on one connection
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from edgar_fundamentals import config, db
from edgar_fundamentals.dashboard.queries import BENCH_QUERIES
from edgar_fundamentals.log import get_logger

log = get_logger("edgar.bench.plans")

_COLD_PLAN_SCRIPT = """
import json, sys, time
from edgar_fundamentals import db
from edgar_fundamentals.dashboard.queries import BENCH_QUERIES
name = sys.argv[1]
sql, params = BENCH_QUERIES[name]
con = db.connect(read_only=True)
t0 = time.perf_counter()
rows = con.execute("EXPLAIN ANALYZE " + sql, params).fetchall()
ms = (time.perf_counter() - t0) * 1000
con.close()
print(json.dumps({"ms": ms, "plan": rows[0][1]}))
"""

# Each variant runs in its own fresh process: the statement is executed first, then the full
# company_search, so the output shows which statement absorbs the one-time cost.
_BISECT_VARIANTS = {
    "literal_ilike_scan_of_dim_company": ("SELECT cik, name FROM dim_company WHERE name ILIKE '%micro%'", []),
    "literal_order_by_limit": ("SELECT cik, name FROM dim_company ORDER BY n_in_scope_filings DESC, length(name), name LIMIT 25", []),
    "select_1_literal": ("SELECT 1", []),
    "param_ilike_only": ("SELECT cik, name FROM dim_company WHERE name ILIKE '%' || $1 || '%'", ["micro"]),
    "param_cik_cast_only": ("SELECT cik, name FROM dim_company WHERE CAST(cik AS VARCHAR) = $1", ["micro"]),
    "param_int_no_table": ("SELECT $1::INT", [1]),
    "explain_full_query": ("EXPLAIN " + BENCH_QUERIES["company_search"][0], ["micro"]),
    "full_company_search": BENCH_QUERIES["company_search"],
}

_BISECT_SCRIPT = """
import json, sys, time
from edgar_fundamentals import db
from edgar_fundamentals.dashboard.queries import BENCH_QUERIES
from edgar_fundamentals.bench.plans import _BISECT_VARIANTS
variant = sys.argv[1]
preimport = sys.argv[2] if len(sys.argv) > 2 else ""
imp_ms = 0.0
if preimport:
    t0 = time.perf_counter(); __import__(preimport); imp_ms = (time.perf_counter() - t0) * 1000
con = db.connect(read_only=True)
before = set(sys.modules)
sql, params = _BISECT_VARIANTS[variant]
t0 = time.perf_counter(); con.execute(sql, params).fetchall(); first_ms = (time.perf_counter() - t0) * 1000
new_top = sorted({m.split('.')[0] for m in set(sys.modules) - before if not m.startswith('_')})
fsql, fparams = BENCH_QUERIES["company_search"]
t0 = time.perf_counter(); con.execute(fsql, fparams).fetchall(); then_ms = (time.perf_counter() - t0) * 1000
con.close()
print(json.dumps({"variant": variant, "preimport": preimport, "preimport_ms": imp_ms, "first_ms": first_ms,
                  "then_company_search_ms": then_ms, "modules_imported_by_first": new_top}))
"""


def _fresh(script: str, *args: str) -> dict:
    res = subprocess.run([sys.executable, "-c", script, *args], capture_output=True, text=True, check=True,
                         cwd=str(config.PROJECT_ROOT))
    return json.loads(res.stdout.strip().splitlines()[-1])


def save_plans(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, dict] = {}
    con = db.connect(read_only=True)
    try:
        for name, (sql, params) in BENCH_QUERIES.items():
            cold = _fresh(_COLD_PLAN_SCRIPT, name)
            (out_dir / f"{name}.cold.txt").write_text(
                f"-- {name} | COLD: EXPLAIN ANALYZE as the first statement of a fresh process + fresh read-only connection\n"
                f"-- wall-clock of the EXPLAIN ANALYZE call as seen from Python: {cold['ms']:.1f} ms\n"
                f"-- params: {params!r}\n{sql}\n\n{cold['plan']}", encoding="utf-8")
            for _ in range(5):
                con.execute(sql, params).fetchall()
            t0 = time.perf_counter()
            rows = con.execute("EXPLAIN ANALYZE " + sql, params).fetchall()
            warm_ms = (time.perf_counter() - t0) * 1000
            (out_dir / f"{name}.warm.txt").write_text(
                f"-- {name} | WARM: EXPLAIN ANALYZE after 5 executions on the same connection\n"
                f"-- wall-clock of the EXPLAIN ANALYZE call as seen from Python: {warm_ms:.1f} ms\n"
                f"-- params: {params!r}\n{sql}\n\n{rows[0][1]}", encoding="utf-8")
            summary[name] = {"cold_explain_ms": cold["ms"], "warm_explain_ms": warm_ms}
            log.info("plans saved: %-24s cold %.1f ms, warm %.1f ms", name, cold["ms"], warm_ms)
    finally:
        con.close()
    return summary


def bisect_company_search(out_dir: Path) -> list[dict]:
    """Which statement absorbs the one-time cost? Each line is a fresh process."""
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for variant in _BISECT_VARIANTS:
        results.append(_fresh(_BISECT_SCRIPT, variant))
    for mod in ("numpy", "pandas"):
        results.append(_fresh(_BISECT_SCRIPT, "full_company_search", mod))
    lines = ["company_search cold-cost bisection. Every line is a fresh Python process + fresh read-only connection.",
             "'first' = the variant statement executed first; 'then' = the full company_search executed second.",
             ""]
    for r in results:
        pre = f"pre-import {r['preimport']} ({r['preimport_ms']:.0f} ms), then " if r["preimport"] else ""
        lines.append(f"{pre}{r['variant']:36s} first={r['first_ms']:7.1f} ms  then company_search={r['then_company_search_ms']:6.1f} ms"
                     f"  modules imported by first: {', '.join(r['modules_imported_by_first']) or '-'}")
    (out_dir / "company_search_bisection.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out_dir / "company_search_bisection.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    for line in lines:
        log.info("%s", line)
    return results
