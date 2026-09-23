"""R19 fiscal period validity, R20 referential integrity, R21 instant/duration."""
from __future__ import annotations

from tests.schema import add_fact, add_filing, add_tag

A = "0000000001-25-000001"


def test_R19_fiscal_period_validity(con, run_rule):
    add_filing(con, A, form="10-K", period="2024-12-31", filed="2025-02-15", fy=2024, fp="FY")
    add_filing(con, "0000000001-25-000002", form="10-Q", period="2025-03-31", filed="2025-05-10", fy=2025, fp="Q1")
    add_filing(con, "0000000001-25-000003", form="10-K", period="2024-12-31", filed="2025-02-15", fy=2019, fp="Q2")
    add_filing(con, "0000000001-25-000004", form="10-Q", period="2025-09-30", filed="2025-05-10", fy=2025, fp="Q3")
    add_filing(con, "0000000001-25-000005", form="8-K", period="2025-09-30", filed="2025-05-10", fy=2025, fp="ZZ", in_scope=False)
    s, fails = run_rule("fiscal_period_validity")
    assert (s["passed"], s["failed"]) == (2, 2)
    msgs = dict(zip(fails["adsh"], fails["message"]))
    assert "fy=2019" in msgs["0000000001-25-000003"] and "10-K with fp=Q2" in msgs["0000000001-25-000003"]
    assert msgs["0000000001-25-000004"] == "period after filing date"


def test_R20_tag_referential_integrity(con, run_rule):
    con.execute("INSERT INTO raw_tag VALUES ('Assets', 'us-gaap/2024', 0, 0, 'monetary', 'I', 'D', 'Assets', '', '2025q1')")
    con.execute("INSERT INTO raw_sub VALUES (?, 1, 'X', 1, '1231', '10-K', '20241231', 2024, 'FY', '20250215', 0, '2025q1')", [A])
    ins = "INSERT INTO raw_num VALUES (?, ?, ?, '20241231', 0, 'USD', NULL, NULL, 1.0, NULL, '2025q1')"
    con.execute(ins, [A, "Assets", "us-gaap/2024"])                       # ok
    con.execute(ins, [A, "Assets", "us-gaap/2023"])                       # version missing from tag.txt
    con.execute(ins, ["0000000009-25-000001", "Assets", "us-gaap/2024"])  # accession missing from sub.txt
    con.execute("INSERT INTO raw_pre VALUES (?, 1, 1, 'BS', 0, 'H', 'Assets', 'us-gaap/2024', 'Total assets', 0, '2025q1')", [A])
    con.execute("INSERT INTO raw_pre VALUES (?, 1, 2, 'BS', 0, 'H', 'Nope', 'us-gaap/2024', 'Nope', 0, '2025q1')", [A])
    s, fails = run_rule("tag_referential_integrity")
    assert (s["passed"], s["failed"]) == (2, 3)
    assert sorted(fails["message"].str.split(" ").str[0]) == ["num", "num", "pre"]


def test_R21_instant_duration_consistency(con, run_rule):
    add_tag(con, "Assets", "monetary", "I"); add_tag(con, "Revenues", "monetary", "D")
    add_tag(con, "StockIssuedDuringPeriodSharesNewIssues", "shares", "D")
    add_fact(con, A, "Assets", 1.0, qtrs=0)
    add_fact(con, A, "Revenues", 1.0, qtrs=4)
    add_fact(con, A, "Assets", 1.0, qtrs=4, period_end="2023-12-31")               # fail
    add_fact(con, A, "StockIssuedDuringPeriodSharesNewIssues", 1.0, qtrs=0)         # sub-quarter duration -> skip
    s, fails = run_rule("instant_duration_consistency")
    assert (s["passed"], s["failed"], s["skipped"]) == (2, 1, 1)
    assert fails.iloc[0]["tag"] == "Assets"
