"""Benchmark tooling: the optimization report renders from the saved results, and the plan capture writes
cold/warm EXPLAIN ANALYZE files against the real warehouse."""
from __future__ import annotations

from pathlib import Path

import pytest

from edgar_fundamentals.bench import optimization_report as rep


def test_optimization_report_renders_from_saved_results():
    if not (rep.RESULTS / "00_baseline.json").exists():
        pytest.skip("no saved benchmark results")
    md = rep.render()
    assert "### Noise floor" in md and "| 02 eager" in md
    assert "sector_percentile" in md and "company_search" in md
    assert rep.delta(100.0, 50.0) == "-50.0 (-50%)" and rep.delta(None, 1.0) == "n/a"
    assert rep.f1(1234.56) == "1,234.6" and rep.f1(None) == "n/a"


def test_final_table_signs():
    q = {n: {"cold_p50_ms": 10.0, "cold_p95_ms": 12.0, "warm_p50_ms": 4.0, "warm_p95_ms": 5.0} for n in rep.QUERIES}
    before = {"queries": q, "connect_p50_ms": 20.0, "process_wall_p50_ms": 1000.0, "dashboard": {"cold_ms": 2000.0, "warm_ms": 800.0}}
    after = {"queries": {n: {**v, "cold_p50_ms": 5.0, "warm_p50_ms": 8.0} for n, v in q.items()},
             "connect_p50_ms": 600.0, "process_wall_p50_ms": 1000.0, "dashboard": {"cold_ms": 1000.0, "warm_ms": 800.0}}
    md = rep.final_table(before, after)
    assert "| cold | 10.0 | n/a | 5.0 | +5.0 | +50.0% |" in md      # faster -> positive saved
    assert "| warm | 4.0 | n/a | 8.0 | -4.0 | -100.0% |" in md     # slower -> negative saved
    assert "-580.0 | -2900.0%" in md                                 # connection cost increase is shown, not hidden
    assert "| cold | 2.00 s | n/a | 1.00 s | +1.00 s | +50.0% |" in rep.dashboard_table(before, after)


@pytest.mark.integration
def test_save_plans_writes_cold_and_warm_files(warehouse, tmp_path):
    from edgar_fundamentals.bench import plans

    summary = plans.save_plans(tmp_path)
    assert set(summary) == set(rep.QUERIES)
    for name in rep.QUERIES:
        for phase in ("cold", "warm"):
            text = (tmp_path / f"{name}.{phase}.txt").read_text(encoding="utf-8")
            assert "EXPLAIN ANALYZE" in text.splitlines()[0] and "Total Time" in text
    assert summary["company_search"]["warm_explain_ms"] < 100


def test_optimization_md_renders_all_sections():
    if not (rep.RESULTS / "99_final.json").exists():
        pytest.skip("no final benchmark result")
    from edgar_fundamentals.bench import write_optimization_md as w

    md = w.render()
    for heading in ("## 1. Baseline", "## 2. Diagnosis", "## 3. Changes", "## 4. Final", "## 6. What the speed-up cost",
                    "## 8. Limitations"):
        assert heading in md
    assert "| company_search | 554.5 ms | 614.0 ms | 2.4 ms | 2.5 ms |" in md   # baseline copied verbatim
    assert "no (reverted)" in md and "pytest:" in w.tests_line()
