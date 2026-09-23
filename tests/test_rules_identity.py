"""Identity rules R01, R02, R16, R17, R18: one pass, one fail, one skip each, run through the real SQL."""
from __future__ import annotations

from tests.schema import add_norm

A = "0000000001-25-000001"


def test_R01_balance_sheet_identity(con, run_rule):
    # pass: exact; pass: within 0.1%; fail: 2% off; skip: only one side reported
    add_norm(con, "total_assets", 1000e6, period_end="2024-12-31"); add_norm(con, "liabilities_and_equity", 1000e6, period_end="2024-12-31")
    add_norm(con, "total_assets", 1000e6, period_end="2023-12-31"); add_norm(con, "liabilities_and_equity", 1000.5e6, period_end="2023-12-31")
    add_norm(con, "total_assets", 1000e6, period_end="2022-12-31"); add_norm(con, "liabilities_and_equity", 1020e6, period_end="2022-12-31")
    add_norm(con, "total_assets", 1000e6, period_end="2021-12-31")
    s, fails = run_rule("balance_sheet_identity")
    assert (s["passed"], s["failed"], s["skipped"]) == (2, 1, 1)
    assert fails.iloc[0]["period_end"].strftime("%Y-%m-%d") == "2022-12-31"
    assert fails.iloc[0]["diff"] == -20e6
    assert s["failure_rate"] == 1 / 3 and s["coverage"] == 0.75


def test_R02_liabilities_plus_equity(con, run_rule):
    # pass: L + E + temp = L&E
    add_norm(con, "liabilities_and_equity", 500e6); add_norm(con, "total_liabilities", 300e6)
    add_norm(con, "equity_incl_nci", 190e6); add_norm(con, "temporary_equity", 10e6)
    # fail: 5% gap
    add_norm(con, "liabilities_and_equity", 500e6, period_end="2023-12-31"); add_norm(con, "total_liabilities", 300e6, period_end="2023-12-31")
    add_norm(con, "equity_incl_nci", 175e6, period_end="2023-12-31")
    # skip: total_liabilities derived (would be tautological)
    add_norm(con, "liabilities_and_equity", 500e6, period_end="2022-12-31")
    add_norm(con, "total_liabilities", 300e6, period_end="2022-12-31", status="derived"); add_norm(con, "equity_incl_nci", 200e6, period_end="2022-12-31")
    s, fails = run_rule("liabilities_plus_equity")
    assert (s["passed"], s["failed"], s["skipped"]) == (1, 1, 1)
    assert fails.iloc[0]["observed"] == 475e6 and fails.iloc[0]["expected"] == 500e6


def test_R16_gross_profit_consistency(con, run_rule):
    add_norm(con, "revenue", 100e6, qtrs=4); add_norm(con, "cost_of_revenue", 60e6, qtrs=4); add_norm(con, "gross_profit", 40e6, qtrs=4)
    add_norm(con, "revenue", 100e6, qtrs=4, period_end="2023-12-31"); add_norm(con, "cost_of_revenue", 60e6, qtrs=4, period_end="2023-12-31")
    add_norm(con, "gross_profit", 45e6, qtrs=4, period_end="2023-12-31")
    add_norm(con, "revenue", 100e6, qtrs=4, period_end="2022-12-31"); add_norm(con, "gross_profit", 45e6, qtrs=4, period_end="2022-12-31")
    # a derived gross profit is not a candidate at all
    add_norm(con, "revenue", 100e6, qtrs=4, period_end="2021-12-31"); add_norm(con, "cost_of_revenue", 60e6, qtrs=4, period_end="2021-12-31")
    add_norm(con, "gross_profit", 40e6, qtrs=4, period_end="2021-12-31", status="derived")
    s, fails = run_rule("gross_profit_consistency")
    assert (s["passed"], s["failed"], s["skipped"]) == (1, 1, 1)
    assert fails.iloc[0]["diff"] == -5e6


def test_R17_cash_flow_identity(con, run_rule):
    # pass with FX variant: 50 - 20 - 25 + 1 = 6
    for m, v in [("operating_cash_flow", 50e6), ("investing_cash_flow", -20e6), ("financing_cash_flow", -25e6),
                 ("fx_effect", 1e6), ("cash_change_incl_fx", 6e6)]:
        add_norm(con, m, v, qtrs=4)
    # pass with excl-FX variant: 50 - 20 - 25 = 5
    for m, v in [("operating_cash_flow", 50e6), ("investing_cash_flow", -20e6), ("financing_cash_flow", -25e6),
                 ("cash_change_excl_fx", 5e6)]:
        add_norm(con, m, v, qtrs=4, period_end="2023-12-31")
    # fail: change reported as 9 instead of 5
    for m, v in [("operating_cash_flow", 50e6), ("investing_cash_flow", -20e6), ("financing_cash_flow", -25e6),
                 ("cash_change_excl_fx", 9e6)]:
        add_norm(con, m, v, qtrs=4, period_end="2022-12-31")
    # skip: no change-in-cash tag
    for m, v in [("operating_cash_flow", 50e6), ("investing_cash_flow", -20e6), ("financing_cash_flow", -25e6)]:
        add_norm(con, m, v, qtrs=4, period_end="2021-12-31")
    s, fails = run_rule("cash_flow_identity")
    assert (s["passed"], s["failed"], s["skipped"]) == (2, 1, 1)
    assert "excl_fx" in fails.iloc[0]["message"]


def test_R18_eps_consistency(con, run_rule):
    add_norm(con, "net_income", 100e6, qtrs=4); add_norm(con, "weighted_shares_basic", 50e6, qtrs=4, datatype="shares")
    add_norm(con, "eps_basic", 2.0, qtrs=4, datatype="perShare")
    # fail: EPS reported as if shares were in thousands
    add_norm(con, "net_income", 100e6, qtrs=4, period_end="2023-12-31"); add_norm(con, "weighted_shares_basic", 50e3, qtrs=4, datatype="shares", period_end="2023-12-31")
    add_norm(con, "eps_basic", 2.0, qtrs=4, datatype="perShare", period_end="2023-12-31")
    # skip: shares missing
    add_norm(con, "net_income", 100e6, qtrs=4, period_end="2022-12-31"); add_norm(con, "eps_basic", 2.0, qtrs=4, datatype="perShare", period_end="2022-12-31")
    s, fails = run_rule("eps_consistency")
    assert (s["passed"], s["failed"], s["skipped"]) == (1, 1, 1)
    assert fails.iloc[0]["observed"] == 2000.0
