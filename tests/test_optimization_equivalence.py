"""Optimized dashboard queries must return IDENTICAL answers to the original ones on the real warehouse:
same companies, same ratio values, same percentile ranks, same sector medians. Three real companies in at
least two SIC divisions. Skipped when the warehouse is not built."""
from __future__ import annotations

import math

import pytest

from edgar_fundamentals.dashboard import queries as q
from tests import reference_sector as ref

pytestmark = pytest.mark.integration

FOCUS = {320193: "APPLE", 789019: "MICROSOFT", 19617: "JPMORGAN"}


@pytest.fixture(scope="module")
def focus_sectors(warehouse):
    rows = warehouse.execute("SELECT cik, name, sector FROM dim_company WHERE cik IN (320193, 789019, 19617)").fetchall()
    assert len(rows) == 3, rows
    for cik, name, _ in rows:
        assert FOCUS[cik] in name.upper()
    sectors = {r[2] for r in rows}
    assert len(sectors) >= 2, sectors
    return {r[0]: r[2] for r in rows}


@pytest.fixture(scope="module")
def v0_by_sector(warehouse, focus_sectors):
    return {s: warehouse.execute(q.SECTOR_PERCENTILE_V0, [s]).df() for s in set(focus_sectors.values())}


@pytest.fixture(scope="module")
def new_by_sector(warehouse, focus_sectors):
    return {s: warehouse.execute(q.SECTOR_PERCENTILE, [s]).df() for s in set(focus_sectors.values())}


def test_same_companies_values_and_periods_per_ratio(v0_by_sector, new_by_sector):
    for sector, v0 in v0_by_sector.items():
        new = new_by_sector[sector]
        ratios = sorted(v0["ratio"].unique())
        assert ratios == sorted(new["ratio"].unique()) and len(ratios) == 13
        for ratio in ratios:
            exp = ref.latest_per_company(v0, ratio).set_index("cik").sort_index()
            got = new[new["ratio"] == ratio].set_index("cik").sort_index()
            assert list(got.index) == list(exp.index), (sector, ratio)
            assert got["value"].tolist() == exp["value"].tolist(), (sector, ratio)      # bit-identical values
            assert got["period_end"].tolist() == exp["period_end"].tolist(), (sector, ratio)
            assert got["fiscal_year"].tolist() == exp["fiscal_year"].tolist(), (sector, ratio)


def test_same_percentile_ranks_for_focus_companies(v0_by_sector, new_by_sector, focus_sectors):
    checked = 0
    for cik, sector in focus_sectors.items():
        v0, new = v0_by_sector[sector], new_by_sector[sector]
        for ratio in sorted(new["ratio"].unique()):
            latest = ref.latest_per_company(v0, ratio)
            if cik not in set(latest["cik"]):
                continue
            expected = ref.percentile(latest, cik)
            row = new[(new["ratio"] == ratio) & (new["cik"] == cik)]
            assert len(row) == 1
            assert math.isclose(float(row["pct_rank"].iloc[0]), expected, abs_tol=1e-12), (cik, ratio)
            assert int(row["n_companies"].iloc[0]) == latest["cik"].nunique()
            checked += 1
    assert checked >= 3 * 10


def test_same_percentile_table_for_focus_companies(v0_by_sector, new_by_sector, focus_sectors):
    """The v0 expander listed every ratio in the sector and showed None where the focus company had no FY value;
    the optimized table omits those rows. Every rankable ratio must agree exactly; the omitted ones must be
    exactly the v0 None rows."""
    for cik, sector in focus_sectors.items():
        exp = ref.percentile_table(v0_by_sector[sector], cik).set_index("ratio")
        got = new_by_sector[sector][new_by_sector[sector]["cik"] == cik].set_index("ratio").sort_index()
        rankable = exp[exp["percentile"].notna()]
        assert list(got.index) == list(rankable.index), (cik, sector)
        for ratio in got.index:
            assert math.isclose(got.loc[ratio, "pct_rank"], rankable.loc[ratio, "percentile"], abs_tol=1e-12), (cik, ratio)
            assert got.loc[ratio, "n_companies"] == rankable.loc[ratio, "companies"]


def test_same_sector_median_trend(warehouse, v0_by_sector):
    for sector, v0 in v0_by_sector.items():
        med = warehouse.execute(q.SECTOR_MEDIAN_TREND, [sector]).df()
        for ratio in sorted(v0["ratio"].unique()):
            exp = ref.yearly_median(v0, ratio)
            got = med[med["ratio"] == ratio].set_index("fiscal_year")["median_value"]
            assert list(got.index) == list(exp.index), (sector, ratio)
            for fy in exp.index:
                assert math.isclose(got[fy], exp[fy], abs_tol=1e-9), (sector, ratio, fy)


def test_focus_sources_match_fact_ratios(warehouse, focus_sectors):
    for cik in focus_sectors:
        src = dict(warehouse.execute(q.SECTOR_FOCUS_SOURCES, [cik]).fetchall())
        for ratio, adshs in src.items():
            exp = warehouse.execute("""SELECT source_adshs FROM fact_ratios WHERE cik = ? AND ratio = ? AND basis = 'FY'
                                       AND value IS NOT NULL ORDER BY period_end DESC LIMIT 1""", [cik, ratio]).fetchone()[0]
            assert list(adshs) == list(exp)


def test_unchanged_queries_still_return_fixture_ratios(warehouse, real_filings):
    """company_ratio_trend / multi_company_compare / company_search SQL is unchanged; pin them to the hand-computed fixtures."""
    for f in real_filings["filings"]:
        trend = warehouse.execute(q.COMPANY_RATIO_TREND, [f["cik"]]).df()
        t = trend[(trend["basis"] == f["basis"]) & (trend["period_end"].astype(str) == f["period_end"])].set_index("ratio")
        cmp = warehouse.execute(q.MULTI_COMPANY_COMPARE, [[f["cik"]], f["basis"]]).df()
        c2 = cmp[cmp["period_end"].astype(str) == f["period_end"]].set_index("ratio")
        for ratio, expected in f["expected"].items():
            tol = 0.5 if abs(expected) >= 1000 else 5e-5
            assert t.loc[ratio, "value"] == pytest.approx(expected, abs=tol), (f["name"], ratio)
            assert c2.loc[ratio, "value"] == t.loc[ratio, "value"]
        hit = warehouse.execute(q.COMPANY_SEARCH, [str(f["cik"])]).fetchall()
        assert hit and hit[0][0] == f["cik"]
