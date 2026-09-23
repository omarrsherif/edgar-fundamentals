from __future__ import annotations

from pathlib import Path

import duckdb
import pytest
import yaml

from edgar_fundamentals import config
from edgar_fundamentals.quality import runner as q_runner
from edgar_fundamentals.quality.registry import load_rules, rule_params
from tests import schema

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    schema.create_schema(c)
    yield c
    c.close()


@pytest.fixture(scope="session")
def rules():
    return {r.name: r for r in load_rules()}


@pytest.fixture(scope="session")
def params():
    return rule_params()


@pytest.fixture
def run_rule(con, rules, params):
    """Run one rule by name against the test connection; returns (summary dict, fail rows DataFrame)."""
    from edgar_fundamentals.quality.registry import RESULT_COLUMNS

    cols = ", ".join(f"{c} {t}" for c, t in RESULT_COLUMNS.items())
    con.execute(f"CREATE TABLE IF NOT EXISTS dq_results (rule_id VARCHAR, rule_name VARCHAR, category VARCHAR, severity VARCHAR, {cols})")
    con.execute("CREATE TABLE IF NOT EXISTS dq_summary (rule_id VARCHAR, rule_name VARCHAR, category VARCHAR, "
                "severity VARCHAR, unit VARCHAR, description VARCHAR, candidates BIGINT, evaluated BIGINT, "
                "passed BIGINT, failed BIGINT, skipped BIGINT, failure_rate DOUBLE, coverage DOUBLE, "
                "seconds DOUBLE, run_at TIMESTAMP)")

    def _run(name: str):
        q_runner.prepare(con)
        summary = q_runner.run_rule(con, rules[name], params)
        fails = con.execute("SELECT * FROM dq_results WHERE rule_name = ?", [name]).df()
        con.execute("DELETE FROM dq_results WHERE rule_name = ?", [name])
        return summary, fails

    return _run


@pytest.fixture(scope="session")
def real_filings() -> dict:
    with open(FIXTURES / "real_filings.yaml", "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="session")
def warehouse():
    """Read-only connection to the built warehouse; skips the test when it does not exist."""
    p = config.path("warehouse")
    if not p.exists():
        pytest.skip("warehouse not built (run `edgar-fundamentals all`)")
    c = duckdb.connect(str(p), read_only=True)
    yield c
    c.close()
