"""Benchmark the five dashboard queries and the dashboard load.

cold  = a fresh Python process and a fresh read-only DuckDB connection per run (DuckDB's buffer pool is
        empty; the operating-system page cache is NOT dropped, which is stated in the report)
warm  = repeated execution on one open connection after warm-up runs
dashboard load = wall-clock of the Streamlit script's first (cold, fresh process) and second (warm) run
        via streamlit.testing.v1.AppTest, i.e. server-side execution without browser rendering.
"""
from __future__ import annotations

import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

from edgar_fundamentals import config, db
from edgar_fundamentals.dashboard.queries import BENCH_QUERIES
from edgar_fundamentals.log import get_logger

log = get_logger("edgar.bench")

_COLD_SCRIPT = """
import json, sys, time
from edgar_fundamentals import db
from edgar_fundamentals.dashboard.queries import BENCH_QUERIES
t_open = time.perf_counter()
con = db.connect(read_only=True)
open_ms = (time.perf_counter() - t_open) * 1000
out = {"_connect_ms": open_ms}
for name, (sql, params) in BENCH_QUERIES.items():
    t0 = time.perf_counter()
    con.execute(sql, params).fetchall()
    out[name] = (time.perf_counter() - t0) * 1000
con.close()
print(json.dumps(out))
"""

_APPTEST_SCRIPT = """
import json, time, sys
from streamlit.testing.v1 import AppTest
path = sys.argv[1]
t0 = time.perf_counter()
at = AppTest.from_file(path, default_timeout=300)
at.run()
cold = (time.perf_counter() - t0) * 1000
assert not at.exception, at.exception
t1 = time.perf_counter()
at.run()
warm = (time.perf_counter() - t1) * 1000
print(json.dumps({"cold_ms": cold, "warm_ms": warm, "exception": [str(e) for e in at.exception]}))
"""


def pct(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    k = (len(s) - 1) * p
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def run_cold(n: int) -> dict[str, list[float]]:
    times: dict[str, list[float]] = {k: [] for k in list(BENCH_QUERIES) + ["_connect_ms", "_process_wall_ms"]}
    for i in range(n):
        t0 = time.perf_counter()
        res = subprocess.run([sys.executable, "-c", _COLD_SCRIPT], capture_output=True, text=True, check=True,
                             cwd=str(config.PROJECT_ROOT))
        wall = (time.perf_counter() - t0) * 1000
        data = json.loads(res.stdout.strip().splitlines()[-1])
        for k, v in data.items():
            times[k].append(v)
        times["_process_wall_ms"].append(wall)
        log.info("cold run %d/%d: %s", i + 1, n, ", ".join(f"{k}={v:.0f}ms" for k, v in data.items()))
    return times


def run_warm(n: int, warmups: int = 5) -> dict[str, list[float]]:
    con = db.connect(read_only=True)
    times: dict[str, list[float]] = {k: [] for k in BENCH_QUERIES}
    try:
        for name, (sql, params) in BENCH_QUERIES.items():
            for _ in range(warmups):
                con.execute(sql, params).fetchall()
            for _ in range(n):
                t0 = time.perf_counter()
                con.execute(sql, params).fetchall()
                times[name].append((time.perf_counter() - t0) * 1000)
            log.info("warm %-24s p50=%.1fms p95=%.1fms (n=%d)", name, pct(times[name], 0.5), pct(times[name], 0.95), n)
    finally:
        con.close()
    return times


def run_dashboard_load() -> dict:
    app = Path(__file__).resolve().parents[1] / "dashboard" / "app.py"
    res = subprocess.run([sys.executable, "-c", _APPTEST_SCRIPT, str(app)], capture_output=True, text=True,
                         cwd=str(config.PROJECT_ROOT))
    if res.returncode != 0:
        log.error("dashboard load measurement failed:\n%s", res.stderr[-3000:])
        return {"cold_ms": None, "warm_ms": None, "error": res.stderr[-2000:]}
    data = json.loads(res.stdout.strip().splitlines()[-1])
    log.info("dashboard server-side script run: cold=%.0fms warm=%.0fms", data["cold_ms"], data["warm_ms"])
    return data


def run_benchmarks(cold_runs: int = 20, warm_runs: int = 50) -> dict:
    cold = run_cold(cold_runs)
    warm = run_warm(warm_runs)
    rows = {}
    for name in BENCH_QUERIES:
        rows[name] = {
            "cold_p50_ms": pct(cold[name], 0.5), "cold_p95_ms": pct(cold[name], 0.95),
            "warm_p50_ms": pct(warm[name], 0.5), "warm_p95_ms": pct(warm[name], 0.95),
            "cold_n": len(cold[name]), "warm_n": len(warm[name]),
        }
    result = {
        "queries": rows,
        "connect_p50_ms": pct(cold["_connect_ms"], 0.5),
        "process_wall_p50_ms": pct(cold["_process_wall_ms"], 0.5),
        "dashboard": run_dashboard_load(),
        "definitions": {
            "cold": "fresh Python process + fresh read-only DuckDB connection per run; OS page cache not dropped",
            "warm": f"same connection, {warm_runs} timed runs after 5 warm-ups",
            "dashboard": "streamlit.testing.v1.AppTest full script execution (server side, no browser render); "
                         "cold = first run in a fresh process, warm = second run in the same process",
        },
    }
    out = config.path("reports_dir") / "bench.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    log.info("bench written -> %s", out)
    return result
