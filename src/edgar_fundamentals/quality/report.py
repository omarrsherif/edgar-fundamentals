"""Render the data-quality report (Markdown + JSON) from dq_summary / dq_results."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from edgar_fundamentals import config, db


def collect(con: duckdb.DuckDBPyConnection) -> dict:
    rules = con.execute("SELECT * FROM dq_summary ORDER BY rule_id").df().to_dict(orient="records")
    total_eval = sum(r["evaluated"] for r in rules)
    total_fail = sum(r["failed"] for r in rules)
    categories = con.execute("""
        SELECT category, sum(failed) AS failed, sum(evaluated) AS evaluated
        FROM dq_summary GROUP BY category ORDER BY failed DESC
    """).df().to_dict(orient="records")
    for c in categories:
        c["share_of_failures"] = (c["failed"] / total_fail) if total_fail else 0.0
    top_companies = con.execute("""
        SELECT r.cik, c.name, count(*) AS failures, count(DISTINCT r.rule_id) AS rules_hit
        FROM dq_results r JOIN dim_company c USING (cik)
        WHERE r.severity IN ('error', 'warn')
        GROUP BY ALL ORDER BY failures DESC LIMIT 10
    """).df().to_dict(orient="records")
    restatements = con.execute("""
        SELECT count(DISTINCT (cik, tag, period_end, qtrs, uom)) FILTER (WHERE classification = 'restatement') AS restatement_groups,
               count(DISTINCT (cik, tag, period_end, qtrs, uom)) FILTER (WHERE classification = 'rounding_diff') AS rounding_groups,
               count(*) AS version_rows,
               count(DISTINCT cik) FILTER (WHERE classification = 'restatement') AS companies_with_restatements
        FROM restatements
    """).df().iloc[0].to_dict()
    outliers = con.execute("SELECT failed FROM dq_summary WHERE rule_name = 'outlier_robust_z'").fetchone()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rules_implemented": len(rules),
        "total_evaluated": int(total_eval),
        "total_failed": int(total_fail),
        "overall_pass_rate": (1 - total_fail / total_eval) if total_eval else None,
        "rules": rules,
        "categories": categories,
        "top_companies": top_companies,
        "restatements": {k: int(v) for k, v in restatements.items()},
        "outliers_flagged": int(outliers[0]) if outliers else 0,
    }


def _pct(x) -> str:
    return "n/a" if x is None or x != x else f"{x:.3%}"


def render_markdown(d: dict) -> str:
    lines = [
        "# Data quality report", "",
        f"Generated {d['generated_at']}. {d['rules_implemented']} rules; "
        f"{d['total_evaluated']:,} units evaluated; {d['total_failed']:,} failures; "
        f"overall pass rate **{_pct(d['overall_pass_rate'])}**.", "",
        "Failure rate = failed / (passed + failed). Coverage = evaluated / (evaluated + skipped), "
        "where a unit is skipped when the rule's inputs are not reported.", "",
        "## Per rule", "",
        "| id | rule | category | severity | unit | evaluated | passed | failed | skipped | failure rate | coverage |",
        "|---|---|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in d["rules"]:
        lines.append(
            f"| {r['rule_id']} | `{r['rule_name']}` | {r['category']} | {r['severity']} | {r['unit']} | "
            f"{r['evaluated']:,} | {r['passed']:,} | {r['failed']:,} | {r['skipped']:,} | "
            f"{_pct(r['failure_rate'])} | {_pct(r['coverage'])} |"
        )
    lines += ["", "## Top failure categories (share of failing rows)", "",
              "| category | failed | evaluated | share of all failures |", "|---|---:|---:|---:|"]
    for c in d["categories"]:
        lines.append(f"| {c['category']} | {int(c['failed']):,} | {int(c['evaluated']):,} | {_pct(c['share_of_failures'])} |")
    rs = d["restatements"]
    lines += ["", "## Restatements", "",
              f"- {rs['restatement_groups']:,} (company, tag, period, duration, unit) facts reported with materially "
              f"different values in different filings, across {rs['companies_with_restatements']:,} companies; "
              f"{rs['version_rows']:,} version rows kept, later filing marked authoritative.",
              f"- {rs['rounding_groups']:,} further facts differ only within the rounding tolerance.",
              "", f"## Outliers", "", f"- {d['outliers_flagged']:,} normalized values flagged beyond the robust z threshold.",
              "", "## Companies with most failures (error/warn)", "",
              "| cik | company | failures | rules hit |", "|---|---|---:|---:|"]
    for c in d["top_companies"]:
        lines.append(f"| {c['cik']} | {c['name']} | {int(c['failures']):,} | {int(c['rules_hit'])} |")
    lines += ["", "## Rule descriptions", ""]
    for r in d["rules"]:
        lines.append(f"- **{r['rule_id']} `{r['rule_name']}`** - {r['description']}")
    return "\n".join(lines) + "\n"


def write(con: duckdb.DuckDBPyConnection | None = None, out_dir: Path | None = None) -> dict:
    own = con is None
    con = con or db.connect(read_only=True)
    out_dir = out_dir or config.path("reports_dir")
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        d = collect(con)
    finally:
        if own:
            con.close()
    (out_dir / "data_quality.md").write_text(render_markdown(d), encoding="utf-8")
    (out_dir / "data_quality.json").write_text(json.dumps(d, indent=2, default=str), encoding="utf-8")
    return d
