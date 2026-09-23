"""The precomputed sector tables must reproduce the original per-request pandas logic exactly
(synthetic data with ties, nulls, a missing year, a Q-basis row that must be ignored, and two sectors)."""
from __future__ import annotations

import math

import pytest

from edgar_fundamentals.dashboard.queries import SECTOR_PERCENTILE, SECTOR_PERCENTILE_V0
from edgar_fundamentals.ratios.sector import build_sector_tables
from tests import reference_sector as ref
from tests.schema import add_company, add_ratio


@pytest.fixture
def sector_db(con):
    # Manufacturing: 5 companies, Services: 2 companies
    for cik, sector in [(1, "Manufacturing"), (2, "Manufacturing"), (3, "Manufacturing"), (4, "Manufacturing"),
                        (5, "Manufacturing"), (6, "Services"), (7, "Services")]:
        add_company(con, cik=cik, name=f"CO {cik}", sector=sector, industry="X")
    # gross_margin history; company 1 ties with company 2 on its latest value; company 5 has only a null
    add_ratio(con, 1, "gross_margin", 0.40, "2023-12-31"); add_ratio(con, 1, "gross_margin", 0.45, "2024-12-31")
    add_ratio(con, 2, "gross_margin", 0.45, "2024-12-31")
    add_ratio(con, 3, "gross_margin", 0.10, "2022-12-31"); add_ratio(con, 3, "gross_margin", 0.30, "2024-12-31")
    add_ratio(con, 3, "gross_margin", 0.99, "2024-12-31", basis="Q")          # Q basis must be ignored
    add_ratio(con, 4, "gross_margin", 0.60, "2023-12-31")                       # latest is 2023, not 2024
    add_ratio(con, 4, "gross_margin", None, "2024-12-31", reason="missing:revenue")
    add_ratio(con, 5, "gross_margin", None, "2024-12-31", reason="missing:revenue")
    add_ratio(con, 6, "gross_margin", 0.20, "2024-06-30"); add_ratio(con, 7, "gross_margin", 0.80, "2024-06-30")
    # roa: only two companies in Manufacturing
    add_ratio(con, 1, "roa", 0.05, "2024-12-31"); add_ratio(con, 3, "roa", -0.02, "2024-12-31")
    build_sector_tables(con)
    return con


def _v0(con, sector):
    return con.execute(SECTOR_PERCENTILE_V0, [sector]).df()


def _new(con, sector):
    return con.execute(SECTOR_PERCENTILE, [sector]).df()


def test_latest_value_and_company_set_identical(sector_db):
    for sector in ("Manufacturing", "Services"):
        v0, new = _v0(sector_db, sector), _new(sector_db, sector)
        for ratio in sorted(new["ratio"].unique()):
            ref_latest = ref.latest_per_company(v0, ratio).set_index("cik").sort_index()
            got = new[new["ratio"] == ratio].set_index("cik").sort_index()
            assert list(got.index) == list(ref_latest.index)
            assert got["value"].tolist() == ref_latest["value"].tolist()
            assert got["period_end"].tolist() == ref_latest["period_end"].tolist()
            assert got["fiscal_year"].tolist() == ref_latest["fiscal_year"].tolist()
    # company 5 (only nulls) is absent; company 4 is present with its 2023 value
    m = _new(sector_db, "Manufacturing")
    gm = m[m["ratio"] == "gross_margin"].set_index("cik")
    assert 5 not in gm.index and gm.loc[4, "value"] == 0.60 and str(gm.loc[4, "period_end"])[:10] == "2023-12-31"


def test_percentile_identical_including_ties(sector_db):
    v0 = _v0(sector_db, "Manufacturing")
    new = _new(sector_db, "Manufacturing")
    latest = ref.latest_per_company(v0, "gross_margin")
    for cik in (1, 2, 3, 4):
        expected = ref.percentile(latest, cik)
        got = float(new[(new["ratio"] == "gross_margin") & (new["cik"] == cik)]["pct_rank"].iloc[0])
        assert math.isclose(got, expected, abs_tol=1e-12), (cik, got, expected)
    # tie: companies 1 and 2 both 0.45 -> one company (0.30) strictly lower out of 4 -> 0.25 for both
    assert ref.percentile(latest, 1) == 0.25 and ref.percentile(latest, 2) == 0.25
    assert new[(new["ratio"] == "gross_margin") & (new["cik"] == 1)]["n_companies"].iloc[0] == 4


def test_percentile_table_identical(sector_db):
    v0 = _v0(sector_db, "Manufacturing")
    new = _new(sector_db, "Manufacturing")
    for focus in (1, 3):
        expected = ref.percentile_table(v0, focus).set_index("ratio")
        got = new[new["cik"] == focus].set_index("ratio").sort_index()
        assert list(got.index) == list(expected.index)
        for ratio in got.index:
            assert math.isclose(got.loc[ratio, "pct_rank"], expected.loc[ratio, "percentile"], abs_tol=1e-12)
            assert got.loc[ratio, "n_companies"] == expected.loc[ratio, "companies"]


def test_yearly_median_identical(sector_db):
    v0 = _v0(sector_db, "Manufacturing")
    expected = ref.yearly_median(v0, "gross_margin")
    got = dict(sector_db.execute(
        "SELECT fiscal_year, median_value FROM sector_ratio_yearly WHERE sector = 'Manufacturing' AND ratio = 'gross_margin'"
    ).fetchall())
    assert set(got) == set(expected.index)
    for fy, med in expected.items():
        assert math.isclose(got[fy], med, abs_tol=1e-9)
    assert got[2024] == pytest.approx(0.45, abs=1e-12)                 # 0.30, 0.45, 0.45 (nulls excluded)
    assert got[2023] == pytest.approx((0.40 + 0.60) / 2, abs=1e-12)   # even count -> mean of the middle pair


def test_no_list_column_in_optimized_query(sector_db):
    cols = [d[0] for d in sector_db.execute(SECTOR_PERCENTILE, ["Manufacturing"]).description]
    assert "source_adshs" not in cols and "industry" not in cols and {"pct_rank", "n_companies"} <= set(cols)
