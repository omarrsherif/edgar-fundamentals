"""R09 restatement detection (through the real restatements SQL), R10 amendments, R11/R12 duplicates."""
from __future__ import annotations

from edgar_fundamentals import config, db
from edgar_fundamentals.warehouse.runner import sql_params
from tests.schema import add_fact, add_filing

A1 = "0000000001-24-000001"   # original 10-K, filed 2024-02-15
A2 = "0000000001-25-000001"   # next year's 10-K, filed 2025-02-15 (carries comparatives)
A3 = "0000000001-24-000002"   # 10-K/A, filed 2024-06-01


def build_restatements(con):
    db.run_sql_file(con, config.SQL_DIR / "050_restatements.sql", sql_params())


def test_restatements_table_keeps_both_and_marks_latest_authoritative(con):
    add_fact(con, A1, "Revenues", 100.0, filed="2024-02-15")
    add_fact(con, A2, "Revenues", 110.0, filed="2025-02-15")            # revised in the later filing
    add_fact(con, A1, "Assets", 500.0, filed="2024-02-15")
    add_fact(con, A2, "Assets", 500.3, filed="2025-02-15")              # rounding difference only
    add_fact(con, A1, "NetIncomeLoss", 7.0, filed="2024-02-15")
    add_fact(con, A2, "NetIncomeLoss", 7.0, filed="2025-02-15")         # identical -> not a restatement
    build_restatements(con)
    rows = con.execute("SELECT tag, adsh, value, is_authoritative, authoritative_value, classification, n_versions "
                       "FROM restatements ORDER BY tag, filed").fetchall()
    assert [r[0] for r in rows] == ["Assets", "Assets", "Revenues", "Revenues"]
    rev = {r[1]: r for r in rows if r[0] == "Revenues"}
    assert rev[A2][3] is True and rev[A1][3] is False
    assert rev[A1][4] == 110.0 and rev[A1][5] == "restatement" and rev[A1][6] == 2
    assets = {r[1]: r for r in rows if r[0] == "Assets"}
    assert assets[A1][5] == "rounding_diff"


def test_amendment_wins_ties_on_filing_date(con):
    add_fact(con, A1, "Revenues", 100.0, filed="2024-02-15")
    add_fact(con, A3, "Revenues", 105.0, form="10-K/A", filed="2024-02-15")
    build_restatements(con)
    auth = con.execute("SELECT adsh FROM restatements WHERE is_authoritative").fetchone()[0]
    assert auth == A3


def test_R09_restatement_detected(con, run_rule):
    add_fact(con, A1, "Revenues", 100.0, filed="2024-02-15"); add_fact(con, A2, "Revenues", 110.0, filed="2025-02-15")
    add_fact(con, A1, "Assets", 500.0, filed="2024-02-15"); add_fact(con, A2, "Assets", 500.0, filed="2025-02-15")
    add_fact(con, A1, "Liabilities", 300.0, filed="2024-02-15")   # single filing -> not a candidate
    build_restatements(con)
    s, fails = run_rule("restatement_detected")
    assert (s["passed"], s["failed"], s["skipped"]) == (1, 1, 0)
    assert fails.iloc[0]["tag"] == "Revenues" and fails.iloc[0]["adsh"] == A2
    assert fails.iloc[0]["observed"] == 110.0 and fails.iloc[0]["expected"] == 100.0


def test_R10_amendment_detected(con, run_rule):
    add_filing(con, A1, form="10-K", period="2023-12-31", filed="2024-02-15")
    add_filing(con, A3, form="10-K/A", period="2023-12-31", filed="2024-06-01")
    add_filing(con, A2, form="10-K", period="2024-12-31", filed="2025-02-15")
    s, fails = run_rule("amendment_detected")
    assert (s["passed"], s["failed"]) == (1, 1)
    assert fails.iloc[0]["adsh"] == A1 and A3 in fails.iloc[0]["message"]


def test_R11_duplicate_filing(con, run_rule):
    add_filing(con, A1, form="10-K", period="2023-12-31", filed="2024-02-15")
    add_filing(con, "0000000001-24-000009", form="10-K", period="2023-12-31", filed="2024-02-20")
    add_filing(con, A3, form="10-K/A", period="2023-12-31", filed="2024-06-01")   # amendment: excluded
    add_filing(con, A2, form="10-K", period="2024-12-31", filed="2025-02-15")
    s, fails = run_rule("duplicate_filing")
    assert (s["passed"], s["failed"]) == (1, 2)


def test_R12_duplicate_fact_rows(con, run_rule):
    row = [A1, "Assets", "us-gaap/2024", "20241231", 0, "USD", None, None, 1.0, None, "2025q1"]
    con.execute("INSERT INTO raw_num VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
    con.execute("INSERT INTO raw_num VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
    con.execute("INSERT INTO raw_num VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", row[:1] + ["Revenues"] + row[2:])
    # same key in a different dataset quarter is not a duplicate
    con.execute("INSERT INTO raw_num VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", row[:-1] + ["2025q2"])
    s, fails = run_rule("duplicate_fact_rows")
    assert (s["passed"], s["failed"]) == (2, 2)
    assert len(fails) == 1 and fails.iloc[0]["n"] == 2 and "2x" in fails.iloc[0]["message"]
