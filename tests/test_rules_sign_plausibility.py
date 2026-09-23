"""Sign and plausibility rules R03, R04, R05, R06, R22."""
from __future__ import annotations

from tests.schema import add_fact, add_norm, add_tag

A = "0000000001-25-000001"


def test_R03_sign_conventions(con, run_rule):
    add_fact(con, A, "Assets", 100.0)
    add_fact(con, A, "InventoryNet", -5.0)                      # fail
    add_fact(con, A, "EntityCommonStockSharesOutstanding", -1.0, version="dei/2024")  # fail (dei-prefixed tag)
    add_fact(con, A, "NetIncomeLoss", -50.0)                    # not in the list -> not a candidate
    add_fact(con, A, "Assets", -1.0, segments="Segment=A;")     # dimensional -> not a candidate
    s, fails = run_rule("sign_conventions")
    assert (s["passed"], s["failed"], s["skipped"]) == (1, 2, 0)
    assert set(fails["tag"]) == {"InventoryNet", "EntityCommonStockSharesOutstanding"}


def test_R04_revenue_nonnegative(con, run_rule):
    add_norm(con, "revenue", 10e6, qtrs=4)
    add_norm(con, "revenue", -3e6, qtrs=4, period_end="2023-12-31", tag="RevenuesNetOfInterestExpense")
    add_norm(con, "net_income", -3e6, qtrs=4)
    s, fails = run_rule("revenue_nonnegative")
    assert (s["passed"], s["failed"]) == (1, 1)
    assert "RevenuesNetOfInterestExpense" in fails.iloc[0]["message"]


def test_R05_current_assets_le_total_assets(con, run_rule):
    add_norm(con, "total_assets", 100e6); add_norm(con, "current_assets", 60e6)
    add_norm(con, "total_assets", 100e6, period_end="2023-12-31"); add_norm(con, "current_assets", 120e6, period_end="2023-12-31")
    add_norm(con, "total_assets", 100e6, period_end="2022-12-31")  # bank: no current assets -> skip
    s, fails = run_rule("current_assets_le_total_assets")
    assert (s["passed"], s["failed"], s["skipped"]) == (1, 1, 1)


def test_R06_current_liabilities_le_total_liabilities(con, run_rule):
    add_norm(con, "total_liabilities", 100e6); add_norm(con, "current_liabilities", 60e6)
    add_norm(con, "total_liabilities", 100e6, period_end="2023-12-31", status="derived"); add_norm(con, "current_liabilities", 101e6, period_end="2023-12-31")
    add_norm(con, "total_liabilities", 100e6, period_end="2022-12-31")
    s, fails = run_rule("current_liabilities_le_total_liabilities")
    assert (s["passed"], s["failed"], s["skipped"]) == (1, 1, 1)
    assert "derived" in fails.iloc[0]["message"]


def test_R22_value_magnitude_plausibility(con, run_rule):
    add_tag(con, "Assets", "monetary"); add_tag(con, "CommonStockSharesOutstanding", "shares"); add_tag(con, "EarningsPerShareBasic", "perShare", "D")
    add_fact(con, A, "Assets", 5e11)
    add_fact(con, A, "Assets", 5e14)                                   # fail: > 1e14 USD
    add_fact(con, A, "Assets", 5e14, uom="JPY", period_end="2023-12-31")  # non-USD monetary: not judged -> pass
    add_fact(con, A, "CommonStockSharesOutstanding", 2e13, uom="shares")  # fail
    add_fact(con, A, "EarningsPerShareBasic", 250000.0, qtrs=4, uom="USD")  # fail
    add_fact(con, A, "EarningsPerShareBasic", 2.5, qtrs=4, uom="USD", period_end="2023-12-31")
    s, fails = run_rule("value_magnitude_plausibility")
    assert (s["passed"], s["failed"]) == (3, 3)
    assert set(fails["tag"]) == {"Assets", "CommonStockSharesOutstanding", "EarningsPerShareBasic"}
