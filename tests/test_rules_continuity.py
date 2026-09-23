"""Continuity rules R07 (YTD chain) and R08 (quarters sum to annual)."""
from __future__ import annotations

from tests.schema import add_norm


def test_R07_period_continuity(con, run_rule):
    # YTD(2) at Jun = Q1 (Mar, qtrs=1) + Q2 (Jun, qtrs=1): 100 + 120 = 220 -> pass
    add_norm(con, "revenue", 100e6, period_end="2024-03-31", qtrs=1)
    add_norm(con, "revenue", 120e6, period_end="2024-06-30", qtrs=1)
    add_norm(con, "revenue", 220e6, period_end="2024-06-30", qtrs=2)
    # YTD(3) at Sep = YTD(2) Jun + Q3 Sep: 220 + 130 = 350, reported 340 -> fail
    add_norm(con, "revenue", 130e6, period_end="2024-09-30", qtrs=1)
    add_norm(con, "revenue", 340e6, period_end="2024-09-30", qtrs=3)
    # FY at Dec (qtrs=4): no Q4 standalone -> skip
    add_norm(con, "revenue", 480e6, period_end="2024-12-31", qtrs=4)
    s, fails = run_rule("period_continuity")
    assert (s["passed"], s["failed"], s["skipped"]) == (1, 1, 1)
    assert fails.iloc[0]["qtrs"] == 3 and fails.iloc[0]["diff"] == -10e6


def test_R08_quarters_sum_to_annual(con, run_rule):
    def q(metric, fy, values, period_ends, annual, annual_ok=True):
        for i, (v, pe) in enumerate(zip(values, period_ends), start=1):
            add_norm(con, metric, v, period_end=pe, qtrs=1, fiscal_year=fy, fiscal_quarter=i)
        add_norm(con, metric, annual, period_end=period_ends[-1], qtrs=4, fiscal_year=fy, fiscal_quarter=4)

    ends = ["2024-03-31", "2024-06-30", "2024-09-30", "2024-12-31"]
    q("revenue", 2024, [100e6, 110e6, 120e6, 130e6], ends, 460e6)          # pass
    q("net_income", 2024, [10e6, 10e6, 10e6, 10e6], ends, 45e6)             # fail: 40 != 45
    # skip: only three quarters reported
    for i, (v, pe) in enumerate(zip([50e6, 50e6, 50e6], ends[:3]), start=1):
        add_norm(con, "operating_income", v, period_end=pe, qtrs=1, fiscal_year=2024, fiscal_quarter=i)
    add_norm(con, "operating_income", 210e6, period_end=ends[3], qtrs=4, fiscal_year=2024, fiscal_quarter=4)
    s, fails = run_rule("quarters_sum_to_annual")
    assert (s["passed"], s["failed"], s["skipped"]) == (1, 1, 1)
    assert fails.iloc[0]["tag"] == "net_income" and fails.iloc[0]["expected"] == 40e6
