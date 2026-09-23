"""Integration: the built warehouse must reproduce the hand-transcribed real filings and behave as designed."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_normalized_values_match_real_filings(warehouse, real_filings):
    for f in real_filings["filings"]:
        for metric, expected in f["inputs"].items():
            if metric == "revenue_prior_year":
                continue
            qtrs = 4 if metric in {"revenue", "cost_of_revenue", "gross_profit", "operating_income", "net_income",
                                   "operating_cash_flow", "capex"} else 0
            row = warehouse.execute(
                "SELECT value, source_adsh FROM fact_normalized WHERE cik = ? AND period_end = ? AND qtrs = ? AND metric = ?",
                [f["cik"], f["period_end"], qtrs, metric]).fetchone()
            assert row is not None, f"{f['name']}: {metric} missing"
            assert row[0] == pytest.approx(expected, abs=0.5), f"{f['name']}: {metric}"


def test_ratios_match_hand_computed(warehouse, real_filings):
    for f in real_filings["filings"]:
        rows = dict(warehouse.execute(
            "SELECT ratio, value FROM fact_ratios WHERE cik = ? AND period_end = ? AND basis = ?",
            [f["cik"], f["period_end"], f["basis"]]).fetchall())
        for ratio, expected in f["expected"].items():
            got = rows.get(ratio)
            assert got is not None, f"{f['name']}: {ratio}"
            tol = 0.5 if abs(expected) >= 1000 else 5e-5
            assert got == pytest.approx(expected, abs=tol), f"{f['name']}: {ratio}"


def test_every_ratio_row_has_value_or_reason(warehouse):
    bad = warehouse.execute("SELECT count(*) FROM fact_ratios WHERE value IS NULL AND (reason IS NULL OR reason = '')").fetchone()[0]
    assert bad == 0
    zero = warehouse.execute("SELECT count(*) FROM fact_ratios WHERE status = 'null' AND value IS NOT NULL").fetchone()[0]
    assert zero == 0


def test_restatements_keep_both_versions_with_single_authoritative(warehouse):
    row = warehouse.execute("""
        SELECT count(*) FILTER (WHERE n_auth <> 1), count(*) FILTER (WHERE n_versions < 2)
        FROM (SELECT cik, tag, period_end, qtrs, uom, count(*) FILTER (WHERE is_authoritative) AS n_auth, count(*) AS n_versions
              FROM restatements GROUP BY ALL)
    """).fetchone()
    assert row == (0, 0)


def test_dq_summary_has_every_rule_file(warehouse):
    from edgar_fundamentals.quality.registry import load_rules

    names = {r.name for r in load_rules()}
    in_db = {r[0] for r in warehouse.execute("SELECT rule_name FROM dq_summary").fetchall()}
    assert names == in_db and len(names) >= 15


def test_normalized_grain_is_unique(warehouse):
    dup = warehouse.execute("""SELECT count(*) FROM (SELECT cik, period_end, qtrs, metric FROM fact_normalized
                               GROUP BY ALL HAVING count(*) > 1)""").fetchone()[0]
    assert dup == 0
