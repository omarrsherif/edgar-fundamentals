"""R13 outliers, R14 mandatory tags, R15 units."""
from __future__ import annotations

from tests.schema import add_company, add_fact, add_filing, add_norm, add_tag

A = "0000000001-25-000001"


def test_R13_outlier_robust_z(con, run_rule):
    # 11 quarterly revenue points around 100 with one 1000x scaling error
    ends = ["2022-03-31", "2022-06-30", "2022-09-30", "2022-12-31", "2023-03-31", "2023-06-30",
            "2023-09-30", "2023-12-31", "2024-03-31", "2024-06-30", "2024-09-30"]
    vals = [100, 102, 98, 101, 99, 103, 100, 97, 101, 100, 100_000]
    for pe, v in zip(ends, vals):
        add_norm(con, "revenue", v * 1e6, period_end=pe, qtrs=1)
    # too little history -> skip
    for pe, v in zip(ends[:3], [5, 6, 500]):
        add_norm(con, "net_income", v * 1e6, period_end=pe, qtrs=1)
    # constant history -> MAD = 0 and mean AD = 0 -> skip
    for pe in ends[:9]:
        add_norm(con, "total_assets", 50e6, period_end=pe, qtrs=0)
    s, fails = run_rule("outlier_robust_z")
    assert s["failed"] == 1 and s["passed"] == 10 and s["skipped"] == 12
    assert fails.iloc[0]["observed"] == 100_000e6 and "robust z" in fails.iloc[0]["message"]


def test_R14_missing_mandatory_tags(con, run_rule):
    add_company(con, cik=1)
    add_company(con, cik=2, is_financial=True, sic=6022)
    core = ["total_assets", "liabilities_and_equity", "equity_parent"]
    # filing 1: complete annual (revenue required because cost_of_revenue is reported)
    add_filing(con, "0000000001-25-000001", cik=1, form="10-K", period="2024-12-31")
    for m in core:
        add_norm(con, m, 1e6, cik=1)
    for m in ["net_income", "operating_cash_flow", "revenue", "cost_of_revenue"]:
        add_norm(con, m, 1e6, cik=1, qtrs=4)
    # filing 2: annual missing operating cash flow and revenue (has cost of revenue) -> fail
    add_filing(con, "0000000001-24-000001", cik=1, form="10-K", period="2023-12-31")
    for m in core:
        add_norm(con, m, 1e6, cik=1, period_end="2023-12-31")
    add_norm(con, "net_income", 1e6, cik=1, qtrs=4, period_end="2023-12-31")
    add_norm(con, "cost_of_revenue", 1e6, cik=1, qtrs=4, period_end="2023-12-31")
    # filing 3: bank 10-Q without revenue -> pass (financial exemption), YTD net income counts
    add_filing(con, "0000000002-25-000001", cik=2, form="10-Q", period="2025-06-30")
    for m in core:
        add_norm(con, m, 1e6, cik=2, period_end="2025-06-30")
    add_norm(con, "net_income", 1e6, cik=2, qtrs=2, period_end="2025-06-30")
    # filing 4: pre-revenue biotech 10-Q: no revenue and no cost of revenue -> pass (conditional)
    add_filing(con, "0000000001-25-000002", cik=1, form="10-Q", period="2025-03-31")
    for m in core:
        add_norm(con, m, 1e6, cik=1, period_end="2025-03-31")
    add_norm(con, "net_income", -1e6, cik=1, qtrs=1, period_end="2025-03-31")
    # filing 5: 10-K/A with no balance sheet at all -> not a candidate
    add_filing(con, "0000000001-25-000003", cik=1, form="10-K/A", period="2022-12-31")
    s, fails = run_rule("missing_mandatory_tags")
    assert (s["passed"], s["failed"], s["skipped"]) == (3, 1, 0)
    assert fails.iloc[0]["message"] == "10-K missing: operating_cash_flow, revenue"


def test_R15_unit_inconsistency(con, run_rule):
    add_tag(con, "Assets", "monetary"); add_tag(con, "CommonStockSharesOutstanding", "shares")
    add_tag(con, "EarningsPerShareBasic", "perShare", "D"); add_tag(con, "EffectiveIncomeTaxRate", "pure", "D")
    add_fact(con, A, "Assets", 1.0, uom="USD")
    add_fact(con, A, "Assets", 1.0, uom="EUR", period_end="2023-12-31")        # same tag, 2 currencies -> extra fail
    add_fact(con, A, "Assets", 1.0, uom="shares", period_end="2022-12-31")     # fail
    add_fact(con, A, "CommonStockSharesOutstanding", 1.0, uom="shares")
    add_fact(con, A, "CommonStockSharesOutstanding", 1.0, uom="USD", period_end="2023-12-31")  # fail
    add_fact(con, A, "EarningsPerShareBasic", 1.0, qtrs=4, uom="USD")          # FSDS: bare currency is correct
    add_fact(con, A, "EffectiveIncomeTaxRate", 0.2, qtrs=4, uom="pure")
    s, fails = run_rule("unit_inconsistency")
    assert (s["passed"], s["failed"]) == (5, 3)
    assert sum(fails["message"].str.contains("several currencies")) == 1
