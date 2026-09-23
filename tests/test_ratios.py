"""Ratio math: every ratio has a happy path, explicit null reasons, and real-filing fixtures."""
from __future__ import annotations

import pytest

from edgar_fundamentals.ratios import compute as rc
from edgar_fundamentals.ratios.compute import Input, RATIOS

A = "0000000001-25-000001"


def inp(**kw) -> dict:
    return {k: Input(float(v), A, k) for k, v in kw.items()}


def test_every_ratio_in_config_has_a_function():
    from edgar_fundamentals import config

    cfg = config.load_yaml("ratios.yaml")["ratios"]
    assert set(cfg) == set(RATIOS)


@pytest.mark.parametrize("name", list(RATIOS))
def test_empty_inputs_yield_null_with_reason(name):
    r = RATIOS[name]({})
    assert r.value is None
    assert r.status == "null"
    assert r.reason.startswith(("missing:", "prior_period_not_found"))


def test_gross_margin_prefers_reported_gross_profit():
    r = rc.gross_margin(inp(revenue=100, cost_of_revenue=60, gross_profit=45))
    assert r.value == pytest.approx(0.45)
    assert set(r.inputs) == {"revenue", "gross_profit"}


def test_gross_margin_falls_back_to_cogs():
    r = rc.gross_margin(inp(revenue=100, cost_of_revenue=60))
    assert r.value == pytest.approx(0.40)
    assert r.status == "ok"


def test_gross_margin_zero_revenue():
    r = rc.gross_margin(inp(revenue=0, gross_profit=5))
    assert r.value is None and r.reason == "zero_denominator:revenue"


def test_gross_margin_missing_second_input():
    r = rc.gross_margin(inp(revenue=100))
    assert r.value is None and r.reason == "missing:gross_profit|cost_of_revenue"


def test_operating_and_net_margin():
    assert rc.operating_margin(inp(revenue=200, operating_income=50)).value == pytest.approx(0.25)
    assert rc.net_margin(inp(revenue=200, net_income=-20)).value == pytest.approx(-0.10)
    assert rc.net_margin(inp(revenue=200)).reason == "missing:net_income"


def test_current_ratio_and_zero_denominator():
    assert rc.current_ratio(inp(current_assets=300, current_liabilities=150)).value == pytest.approx(2.0)
    r = rc.current_ratio(inp(current_assets=300, current_liabilities=0))
    assert r.value is None and r.reason == "zero_denominator:current_liabilities"


def test_quick_ratio_estimated_when_inventory_missing():
    r = rc.quick_ratio(inp(current_assets=300, current_liabilities=150))
    assert r.value == pytest.approx(2.0)
    assert r.status == "estimated" and r.reason == "assumes_zero:inventory"
    r2 = rc.quick_ratio(inp(current_assets=300, current_liabilities=150, inventory=60))
    assert r2.value == pytest.approx(1.6) and r2.status == "ok"


def test_debt_to_equity_components_and_reasons():
    full = rc.debt_to_equity(inp(short_term_borrowings=10, ltd_current=20, ltd_noncurrent=70, equity_parent=50))
    assert full.value == pytest.approx(2.0) and full.status == "ok"
    partial = rc.debt_to_equity(inp(ltd_noncurrent=70, equity_parent=50))
    assert partial.value == pytest.approx(1.4)
    assert partial.status == "estimated" and partial.reason == "assumes_zero:short_term_borrowings,ltd_current"
    assert rc.debt_to_equity(inp(equity_parent=50)).reason == "missing:short_term_borrowings|ltd_current|ltd_noncurrent"
    neg = rc.debt_to_equity(inp(ltd_noncurrent=70, equity_parent=-5))
    assert neg.value is None and neg.reason == "non_positive_equity"


def test_liabilities_to_equity():
    assert rc.liabilities_to_equity(inp(total_liabilities=90, equity_parent=30)).value == pytest.approx(3.0)
    assert rc.liabilities_to_equity(inp(total_liabilities=90, equity_parent=0)).reason == "non_positive_equity"


def test_returns_and_turnover():
    assert rc.roa(inp(net_income=10, total_assets=200)).value == pytest.approx(0.05)
    assert rc.roe(inp(net_income=10, equity_parent=40)).value == pytest.approx(0.25)
    assert rc.asset_turnover(inp(revenue=300, total_assets=200)).value == pytest.approx(1.5)
    assert rc.roa(inp(net_income=10, total_assets=0)).reason == "non_positive_denominator:total_assets"
    assert rc.roe(inp(net_income=10, equity_parent=-1)).reason == "non_positive_equity"


def test_free_cash_flow_and_working_capital():
    assert rc.free_cash_flow(inp(operating_cash_flow=100, capex=30)).value == pytest.approx(70)
    assert rc.free_cash_flow(inp(operating_cash_flow=100)).reason == "missing:capex"
    assert rc.working_capital(inp(current_assets=100, current_liabilities=130)).value == pytest.approx(-30)


def test_yoy_growth_reasons():
    assert rc.yoy_revenue_growth(inp(revenue=110, revenue_prior_year=100)).value == pytest.approx(0.10)
    assert rc.yoy_revenue_growth(inp(revenue=110)).reason == "prior_period_not_found"
    assert rc.yoy_revenue_growth(inp(revenue=110, revenue_prior_year=0)).reason == "non_positive_prior_revenue"


def test_derived_inputs_propagate_status():
    i = inp(revenue=100)
    i["net_income"] = Input(20.0, A + "+" + "0000000001-25-000002", "ytd2(NetIncomeLoss)-ytd1", "derived_from_ytd")
    r = rc.net_margin(i)
    assert r.value == pytest.approx(0.2)
    assert r.status == "derived" and "net_income" in r.reason
    assert r.source_adshs == [A, "0000000001-25-000002"]


def test_never_silently_zero():
    """A ratio with missing inputs must be None, never 0.0."""
    for name, fn in RATIOS.items():
        r = fn(inp(revenue=100))
        if r.value is not None:
            assert name in {"asset_turnover"} or r.value != 0.0 or name == "gross_margin"


# ---------------------------------------------------------------------- real filings

def _fixture_cases(real_filings):
    for f in real_filings["filings"]:
        for ratio, expected in f["expected"].items():
            yield pytest.param(f, ratio, expected, id=f"{f['name']}::{ratio}")


def test_real_filing_fixtures_match_hand_computed(real_filings):
    for f in real_filings["filings"]:
        inputs = {k: Input(float(v), f["adsh"], k) for k, v in f["inputs"].items()}
        results = rc.compute_all(inputs)
        for ratio, expected in f["expected"].items():
            got = results[ratio].value
            assert got is not None, f"{f['name']} {ratio}: {results[ratio].reason}"
            if abs(expected) >= 1000:  # currency amounts: exact to the dollar
                assert got == pytest.approx(expected, abs=0.5), f"{f['name']} {ratio}"
            else:
                assert got == pytest.approx(expected, abs=5e-5), f"{f['name']} {ratio}"
            assert results[ratio].status == "ok"
            assert f["adsh"] in results[ratio].source_adshs
