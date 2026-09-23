"""Streamlit AppTest smoke run: every tab renders without an exception against the built warehouse."""
from __future__ import annotations

from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "src" / "edgar_fundamentals" / "dashboard" / "app.py"


@pytest.mark.integration
def test_dashboard_renders_all_tabs(warehouse):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP), default_timeout=300)
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    assert len(at.tabs) == 5
    # Company tab shows Apple by default with metric tiles and at least one chart
    assert any("APPLE" in t.upper() for t in [h.value for h in at.subheader])
    assert len(at.metric) >= 6
    # Data quality tab shows the rule table
    assert any("Overall pass rate" in m.label for m in at.metric)


def test_queries_are_parameterised_and_named():
    from edgar_fundamentals.dashboard.queries import BENCH_QUERIES

    assert len(BENCH_QUERIES) == 5
    for name, (sql, params) in BENCH_QUERIES.items():
        assert sql.count("$") >= len(params) or not params


def test_edgar_url_format():
    from edgar_fundamentals.dashboard.components import edgar_url

    assert edgar_url(320193, "0000320193-24-000123") == \
        "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/0000320193-24-000123-index.htm"
