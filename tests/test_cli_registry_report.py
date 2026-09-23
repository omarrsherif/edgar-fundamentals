"""CLI parser, rule registry parsing, report rendering, bench percentiles, metrics rendering."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar_fundamentals import cli, config
from edgar_fundamentals.bench.run import pct
from edgar_fundamentals.db import split_statements
from edgar_fundamentals.quality import report
from edgar_fundamentals.quality.registry import load_rules, parse_rule, rule_params


def test_cli_parser_commands():
    p = cli.build_parser()
    a = p.parse_args(["ingest", "--quarters", "2", "--latest", "2025q4", "--force"])
    assert a.command == "ingest" and a.quarters == 2 and a.latest == "2025q4" and a.force
    assert p.parse_args(["bench", "--cold-runs", "3"]).cold_runs == 3
    assert p.parse_args(["metrics", "--no-tests"]).no_tests
    assert p.parse_args(["all"]).func is cli.cmd_all
    with pytest.raises(SystemExit):
        p.parse_args(["nope"])


def test_rules_have_unique_ids_and_full_headers():
    rules = load_rules()
    assert len(rules) >= 15
    assert len({r.id for r in rules}) == len(rules)
    for r in rules:
        assert r.category in {"identity", "sign", "plausibility", "continuity", "restatement", "duplicate",
                              "outlier", "completeness", "unit", "referential"}
        assert r.severity in {"error", "warn", "info"}
        assert "SELECT" in r.sql.upper() and not r.sql.endswith(";")


def test_parse_rule_rejects_missing_header(tmp_path):
    p = tmp_path / "R99_x.sql"
    p.write_text("-- id: R99\n-- name: x\nSELECT 1\n", encoding="utf-8")
    with pytest.raises(ValueError):
        parse_rule(p)


def test_rule_params_render_sql_literals():
    params = rule_params()
    assert "('Assets', NULL)" in params["non_negative_tags"]
    assert "('EntityCommonStockSharesOutstanding', 'dei')" in params["non_negative_tags"]
    assert "'FY'" in params["allowed_fp"]
    assert float(params["outlier_sigma"]) == 5.0


def test_split_statements_respects_quotes_and_comments():
    sql = "SELECT 'a;b' AS x; -- trailing; comment\nSELECT 'it''s;' ;\n"
    assert split_statements(sql) == ["SELECT 'a;b' AS x", "SELECT 'it''s;'"]


def test_report_markdown_renders():
    d = {
        "generated_at": "2026-09-23T00:00:00+00:00", "rules_implemented": 1, "total_evaluated": 10, "total_failed": 1,
        "overall_pass_rate": 0.9,
        "rules": [{"rule_id": "R01", "rule_name": "balance_sheet_identity", "category": "identity", "severity": "error",
                   "unit": "u", "evaluated": 10, "passed": 9, "failed": 1, "skipped": 2, "failure_rate": 0.1,
                   "coverage": 10 / 12, "description": "desc"}],
        "categories": [{"category": "identity", "failed": 1, "evaluated": 10, "share_of_failures": 1.0}],
        "top_companies": [{"cik": 1, "name": "X", "failures": 1, "rules_hit": 1}],
        "restatements": {"restatement_groups": 3, "rounding_groups": 1, "version_rows": 7, "companies_with_restatements": 2},
        "outliers_flagged": 4,
    }
    md = report.render_markdown(d)
    assert "| R01 | `balance_sheet_identity` |" in md and "10.000%" in md and "3 (company, tag" in md


def test_pct_percentiles():
    assert pct([1, 2, 3, 4, 5], 0.5) == 3
    assert pct([1, 2, 3, 4, 5], 0.95) == pytest.approx(4.8)
    assert pct([], 0.5) != pct([], 0.5)  # nan


def test_metrics_template_renders_from_saved_json():
    from edgar_fundamentals.metrics import collect

    p = config.path("reports_dir") / "metrics.json"
    if not p.exists():
        pytest.skip("no metrics.json yet")
    m = json.loads(p.read_text(encoding="utf-8"))
    md = collect.render(m)
    assert "# METRICS" in md and "## Validation" in md and "rows ingested" in md
    assert "edgar-fundamentals METRICS summary" in collect.summary_text(m)
