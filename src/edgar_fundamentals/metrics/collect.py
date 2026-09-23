"""Gather every measured number into reports/metrics.json and render METRICS.md."""
from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Template

from edgar_fundamentals import config, db
from edgar_fundamentals.ingest import manifest
from edgar_fundamentals.log import get_logger

log = get_logger("edgar.metrics")

TEMPLATE = Path(__file__).with_name("METRICS.md.j2")


def dir_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0


def ingest_metrics() -> dict:
    m = manifest.load()["quarters"]
    quarters = sorted(m)
    per_q = []
    for qn in quarters:
        e = m[qn]
        rows = e.get("rows", {})
        per_q.append({
            "quarter": qn, "zip_bytes": e.get("zip_bytes", 0), "download_seconds": e.get("download_seconds", 0.0),
            "extract_seconds": e.get("extract_seconds", 0.0), "parse_seconds": e.get("parse_seconds", 0.0),
            "rows": sum(rows.values()), "rows_num": rows.get("num", 0), "rows_sub": rows.get("sub", 0),
            "rows_tag": rows.get("tag", 0), "rows_pre": rows.get("pre", 0),
            "rejects": sum(e.get("rejects", {}).values()), "rows_per_second": e.get("rows_per_second", 0.0),
            "extracted_bytes": e.get("extracted_bytes", 0), "parquet_bytes": e.get("parquet_bytes", 0),
        })
    total_rows = sum(x["rows"] for x in per_q)
    dl = sum(x["download_seconds"] for x in per_q)
    ex = sum(x["extract_seconds"] for x in per_q)
    pa = sum(x["parse_seconds"] for x in per_q)
    return {
        "quarters": per_q, "n_quarters": len(per_q),
        "first_quarter": quarters[0] if quarters else None, "last_quarter": quarters[-1] if quarters else None,
        "total_rows": total_rows,
        "total_rows_num": sum(x["rows_num"] for x in per_q), "total_rows_sub": sum(x["rows_sub"] for x in per_q),
        "total_rows_tag": sum(x["rows_tag"] for x in per_q), "total_rows_pre": sum(x["rows_pre"] for x in per_q),
        "total_rejects": sum(x["rejects"] for x in per_q),
        "zip_bytes": sum(x["zip_bytes"] for x in per_q), "extracted_bytes": sum(x["extracted_bytes"] for x in per_q),
        "parquet_bytes": sum(x["parquet_bytes"] for x in per_q),
        "download_seconds": dl, "extract_seconds": ex, "parse_seconds": pa, "wall_seconds": dl + ex + pa,
        "rows_per_second_parse": total_rows / pa if pa else 0.0,
        "rows_per_second_end_to_end": total_rows / (dl + ex + pa) if (dl + ex + pa) else 0.0,
    }


def warehouse_metrics() -> dict:
    con = db.connect(read_only=True)
    try:
        counts = dict(con.execute("SELECT table_name, row_count FROM build_log").fetchall())
        build_seconds = con.execute("SELECT build_seconds FROM build_meta").fetchone()[0]
        filings = con.execute("SELECT count(*) FILTER (WHERE in_scope), count(*), count(DISTINCT cik) FILTER (WHERE in_scope), count(DISTINCT cik) FROM dim_filing").fetchone()
        forms = con.execute("SELECT form, count(*) FROM dim_filing WHERE in_scope GROUP BY 1 ORDER BY 2 DESC").fetchall()
        periods = con.execute("SELECT min(period_end), max(period_end) FROM fact_financial_facts WHERE is_current_period").fetchone()
        norm = con.execute("SELECT count(*), count(*) FILTER (WHERE status='derived'), count(DISTINCT metric), count(DISTINCT cik) FROM fact_normalized").fetchone()
        rest = con.execute("""SELECT count(DISTINCT (cik, tag, period_end, qtrs, uom)) FILTER (WHERE classification='restatement'),
                                     count(DISTINCT (cik, tag, period_end, qtrs, uom)) FILTER (WHERE classification='rounding_diff'),
                                     count(DISTINCT cik) FILTER (WHERE classification='restatement'), count(*) FROM restatements""").fetchone()
        ratios = con.execute("""SELECT count(*), count(*) FILTER (WHERE value IS NOT NULL), count(DISTINCT cik),
                                       count(DISTINCT (cik, period_end, basis)), count(DISTINCT ratio) FROM fact_ratios""").fetchone()
        ratio_status = con.execute("SELECT status, count(*) FROM fact_ratios GROUP BY 1 ORDER BY 2 DESC").fetchall()
        null_reasons = con.execute("""SELECT split_part(reason, ':', 1) AS r, count(*) FROM fact_ratios WHERE value IS NULL
                                      GROUP BY 1 ORDER BY 2 DESC LIMIT 6""").fetchall()
        dq = con.execute("SELECT * FROM dq_summary ORDER BY rule_id").df().to_dict(orient="records")
        outliers = next((r["failed"] for r in dq if r["rule_name"] == "outlier_robust_z"), 0)
        total_eval = sum(r["evaluated"] for r in dq)
        total_fail = sum(r["failed"] for r in dq)
        cats = con.execute("SELECT category, sum(failed), sum(evaluated) FROM dq_summary GROUP BY 1 ORDER BY 2 DESC").fetchall()
    finally:
        con.close()
    wh = config.path("warehouse")
    return {
        "table_counts": counts, "build_seconds": build_seconds,
        "filings_in_scope": filings[0], "filings_total": filings[1], "companies_in_scope": filings[2], "companies_total": filings[3],
        "forms": forms, "period_min": str(periods[0]), "period_max": str(periods[1]),
        "normalized_rows": norm[0], "normalized_derived": norm[1], "normalized_metrics": norm[2], "normalized_companies": norm[3],
        "restatement_groups": rest[0], "rounding_groups": rest[1], "restatement_companies": rest[2], "restatement_version_rows": rest[3],
        "ratio_rows": ratios[0], "ratio_non_null": ratios[1], "ratio_companies": ratios[2], "ratio_company_periods": ratios[3], "ratio_count": ratios[4],
        "ratio_status": ratio_status, "ratio_null_reasons": null_reasons,
        "dq_rules": dq, "dq_rules_count": len(dq), "dq_total_evaluated": total_eval, "dq_total_failed": total_fail,
        "dq_pass_rate": (1 - total_fail / total_eval) if total_eval else None,
        "dq_categories": [{"category": c, "failed": int(f), "evaluated": int(e), "share": (f / total_fail) if total_fail else 0} for c, f, e in cats],
        "outliers_flagged": int(outliers),
        "warehouse_bytes": wh.stat().st_size if wh.exists() else 0,
    }


def run_tests() -> dict:
    reports = config.path("reports_dir")
    reports.mkdir(parents=True, exist_ok=True)
    junit = reports / "junit.xml"
    cov = reports / "coverage.json"
    cmd = [sys.executable, "-m", "pytest", "-q", "--cov=edgar_fundamentals", f"--cov-report=json:{cov}",
           f"--junitxml={junit}", "-p", "no:cacheprovider"]
    log.info("running tests: %s", " ".join(cmd[2:]))
    res = subprocess.run(cmd, cwd=str(config.PROJECT_ROOT), capture_output=True, text=True)
    tail = "\n".join(res.stdout.strip().splitlines()[-3:])
    log.info("pytest exit %d: %s", res.returncode, tail)
    out = {"exit_code": res.returncode, "summary_line": tail}
    if junit.exists():
        root = ET.parse(junit).getroot()
        suite = root if root.tag == "testsuite" else root.find("testsuite")
        out.update({k: int(suite.get(k, 0)) for k in ("tests", "failures", "errors", "skipped")})
        out["passed"] = out["tests"] - out["failures"] - out["errors"] - out["skipped"]
        out["seconds"] = float(suite.get("time", 0))
    if cov.exists():
        c = json.loads(cov.read_text(encoding="utf-8"))["totals"]
        out["line_coverage_pct"] = c["percent_covered"]
        out["lines_covered"] = c["covered_lines"]
        out["lines_total"] = c["num_statements"]
    return out


def collect(run_tests_flag: bool = True) -> dict:
    bench_path = config.path("reports_dir") / "bench.json"
    bench = json.loads(bench_path.read_text(encoding="utf-8")) if bench_path.exists() else None
    # Frozen pre-optimization baseline (never overwritten); rendered next to the current numbers.
    baseline_path = config.PROJECT_ROOT / "bench" / "results" / "00_baseline.json"
    bench_baseline = json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path.exists() else None
    # Same-day re-run of the unchanged baseline code (noise floor); see bench/OPTIMIZATION.md section 1a.
    control_path = config.PROJECT_ROOT / "bench" / "results" / "01b_control_rerun2.json"
    bench_control = json.loads(control_path.read_text(encoding="utf-8")) if control_path.exists() else None
    m = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ingest": ingest_metrics(),
        "warehouse": warehouse_metrics(),
        "bench": bench,
        "bench_baseline": bench_baseline,
        "bench_control": bench_control,
        "tests": run_tests() if run_tests_flag else None,
    }
    ing, wh = m["ingest"], m["warehouse"]
    m["storage"] = {
        "zip_bytes": ing["zip_bytes"], "extracted_bytes": ing["extracted_bytes"], "parquet_bytes": ing["parquet_bytes"],
        "warehouse_bytes": wh["warehouse_bytes"],
        "warehouse_vs_zip": wh["warehouse_bytes"] / ing["zip_bytes"] if ing["zip_bytes"] else None,
        "warehouse_vs_extracted": wh["warehouse_bytes"] / ing["extracted_bytes"] if ing["extracted_bytes"] else None,
        "parquet_vs_zip": ing["parquet_bytes"] / ing["zip_bytes"] if ing["zip_bytes"] else None,
        "parquet_vs_extracted": ing["parquet_bytes"] / ing["extracted_bytes"] if ing["extracted_bytes"] else None,
        "extracted_vs_zip": ing["extracted_bytes"] / ing["zip_bytes"] if ing["zip_bytes"] else None,
    }
    return m


def render(m: dict) -> str:
    tpl = Template(TEMPLATE.read_text(encoding="utf-8"))
    return tpl.render(m=m, mb=lambda b: f"{b / 1e6:,.1f} MB", gb=lambda b: f"{b / 1e9:,.2f} GB",
                      pct=lambda x: "n/a" if x is None else f"{100 * x:.2f}%",
                      pct3=lambda x: "n/a" if x is None else f"{100 * x:.3f}%",
                      n=lambda x: f"{int(x):,}", f1=lambda x: f"{x:,.1f}", f2=lambda x: f"{x:,.2f}")


def write_metrics(run_tests: bool = True) -> dict:
    m = collect(run_tests)
    reports = config.path("reports_dir")
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "metrics.json").write_text(json.dumps(m, indent=2, default=str), encoding="utf-8")
    (config.PROJECT_ROOT / "METRICS.md").write_text(render(m), encoding="utf-8")
    log.info("METRICS.md written")
    return m


def summary_text(m: dict) -> str:
    ing, wh, st, b, t = m["ingest"], m["warehouse"], m["storage"], m["bench"], m["tests"]
    lines = [
        "==================== edgar-fundamentals METRICS summary ====================",
        f"quarters ingested            : {ing['n_quarters']} ({ing['first_quarter']} .. {ing['last_quarter']})",
        f"rows ingested (all files)    : {ing['total_rows']:,}  (num {ing['total_rows_num']:,}, sub {ing['total_rows_sub']:,}, tag {ing['total_rows_tag']:,}, pre {ing['total_rows_pre']:,}; rejected {ing['total_rejects']})",
        f"filings covered              : {wh['filings_in_scope']:,} 10-K/10-Q in scope of {wh['filings_total']:,} total submissions",
        f"distinct companies           : {wh['companies_in_scope']:,} in scope of {wh['companies_total']:,} total",
        f"ingest wall-clock            : {ing['wall_seconds']:.1f}s (download {ing['download_seconds']:.1f}s, extract {ing['extract_seconds']:.1f}s, parse {ing['parse_seconds']:.1f}s)",
        f"ingest rows/second           : {ing['rows_per_second_parse']:,.0f} (parse) / {ing['rows_per_second_end_to_end']:,.0f} (end-to-end)",
        f"warehouse build              : {wh['build_seconds']:.1f}s; fact_financial_facts {wh['table_counts'].get('fact_financial_facts', 0):,} rows; fact_normalized {wh['normalized_rows']:,} rows",
        f"warehouse size on disk       : {st['warehouse_bytes'] / 1e6:,.1f} MB DuckDB (+ {st['parquet_bytes'] / 1e6:,.1f} MB Parquet staging)",
        f"compression vs raw ZIPs      : DuckDB/ZIP {st['warehouse_vs_zip']:.2f}x, Parquet/ZIP {st['parquet_vs_zip']:.2f}x; extracted text is {st['extracted_vs_zip']:.1f}x the ZIPs; DuckDB/extracted {st['warehouse_vs_extracted']:.2f}x",
        f"validation rules             : {wh['dq_rules_count']}; overall pass rate {100 * wh['dq_pass_rate']:.3f}% over {wh['dq_total_evaluated']:,} evaluated units ({wh['dq_total_failed']:,} failures)",
    ]
    for r in wh["dq_rules"]:
        fr = "n/a" if r["failure_rate"] is None else f"{100 * r['failure_rate']:.3f}%"
        lines.append(f"  {r['rule_id']} {r['rule_name']:<40} failure rate {fr:>8}  (evaluated {r['evaluated']:,}, skipped {r['skipped']:,})")
    lines += [
        f"restatements detected        : {wh['restatement_groups']:,} facts across {wh['restatement_companies']:,} companies ({wh['restatement_version_rows']:,} version rows kept; {wh['rounding_groups']:,} rounding-only)",
        f"outliers flagged             : {wh['outliers_flagged']:,}",
        f"ratios                       : {wh['ratio_count']} ratios, {wh['ratio_rows']:,} rows ({wh['ratio_non_null']:,} non-null) over {wh['ratio_company_periods']:,} company-periods, {wh['ratio_companies']:,} companies",
    ]
    if b:
        lines.append("query performance (ms)       : cold = fresh process + connection; warm = same connection")
        for name, r in b["queries"].items():
            lines.append(f"  {name:<24} cold p50 {r['cold_p50_ms']:7.1f}  p95 {r['cold_p95_ms']:7.1f} | warm p50 {r['warm_p50_ms']:7.1f}  p95 {r['warm_p95_ms']:7.1f}")
        d = b.get("dashboard") or {}
        if d.get("cold_ms") is not None:
            lines.append(f"dashboard load (server side) : cold {d['cold_ms'] / 1000:.2f}s, warm {d['warm_ms'] / 1000:.2f}s")
    if t:
        lines.append(f"tests                        : {t.get('passed', 0)} passed, {t.get('failures', 0)} failed, {t.get('skipped', 0)} skipped of {t.get('tests', 0)}; line coverage {t.get('line_coverage_pct', 0):.1f}%")
    lines.append("=" * 76)
    return "\n".join(lines)
