"""Minimal warehouse schema for unit tests (same column names/types as the real build)."""
from __future__ import annotations

import duckdb

from edgar_fundamentals.warehouse import aliases

DDL = {
    "raw_sub": """CREATE TABLE raw_sub (adsh VARCHAR, cik BIGINT, name VARCHAR, sic INTEGER, fye VARCHAR,
        form VARCHAR, period VARCHAR, fy INTEGER, fp VARCHAR, filed VARCHAR, prevrpt INTEGER, dataset_quarter VARCHAR)""",
    "raw_num": """CREATE TABLE raw_num (adsh VARCHAR, tag VARCHAR, version VARCHAR, ddate VARCHAR, qtrs INTEGER,
        uom VARCHAR, segments VARCHAR, coreg VARCHAR, value DOUBLE, footnote VARCHAR, dataset_quarter VARCHAR)""",
    "raw_tag": """CREATE TABLE raw_tag (tag VARCHAR, version VARCHAR, custom INTEGER, abstract INTEGER,
        datatype VARCHAR, iord VARCHAR, crdr VARCHAR, tlabel VARCHAR, doc VARCHAR, dataset_quarter VARCHAR)""",
    "raw_pre": """CREATE TABLE raw_pre (adsh VARCHAR, report INTEGER, line INTEGER, stmt VARCHAR, inpth INTEGER,
        rfile VARCHAR, tag VARCHAR, version VARCHAR, plabel VARCHAR, negating INTEGER, dataset_quarter VARCHAR)""",
    "dim_filing": """CREATE TABLE dim_filing (adsh VARCHAR, cik BIGINT, name VARCHAR, sic INTEGER, form VARCHAR,
        period DATE, fy_reported INTEGER, fp_reported VARCHAR, filed DATE, accepted VARCHAR, prevrpt BOOLEAN,
        detail BOOLEAN, nciks INTEGER, aciks VARCHAR, fye VARCHAR, afs VARCHAR, wksi INTEGER, state_of_inc VARCHAR,
        country_of_inc VARCHAR, state_ba VARCHAR, country_ba VARCHAR, dataset_quarter VARCHAR, is_amendment BOOLEAN,
        in_scope BOOLEAN, report_type VARCHAR, edgar_url VARCHAR)""",
    "dim_company": """CREATE TABLE dim_company (cik BIGINT, name VARCHAR, sic INTEGER, sector VARCHAR, industry VARCHAR,
        major_group INTEGER, is_financial BOOLEAN, state_of_inc VARCHAR, country_of_inc VARCHAR, state_ba VARCHAR,
        country_ba VARCHAR, filer_status VARCHAR, fye VARCHAR, fiscal_year_end_month INTEGER,
        fiscal_year_end_assumed BOOLEAN, first_filed DATE, last_filed DATE, n_filings BIGINT,
        n_in_scope_filings BIGINT, n_annual BIGINT, n_quarterly BIGINT)""",
    "dim_tag": """CREATE TABLE dim_tag (tag VARCHAR, version VARCHAR, taxonomy VARCHAR, is_custom BOOLEAN,
        is_abstract BOOLEAN, datatype VARCHAR, iord VARCHAR, crdr VARCHAR, tlabel VARCHAR, doc VARCHAR)""",
    "fact_financial_facts": """CREATE TABLE fact_financial_facts (adsh VARCHAR, cik BIGINT, tag VARCHAR, version VARCHAR,
        taxonomy VARCHAR, is_custom_tag BOOLEAN, period_key VARCHAR, period_end DATE, qtrs INTEGER, uom VARCHAR,
        value DOUBLE, segments VARCHAR, coreg VARCHAR, footnote VARCHAR, form VARCHAR, filed DATE, report_type VARCHAR,
        filing_period DATE, is_consolidated BOOLEAN, is_current_period BOOLEAN, fiscal_year INTEGER,
        fiscal_quarter INTEGER, dataset_quarter VARCHAR)""",
    "fact_normalized": """CREATE TABLE fact_normalized (cik BIGINT, period_end DATE, period_key VARCHAR, qtrs INTEGER,
        fiscal_year INTEGER, fiscal_quarter INTEGER, metric VARCHAR, datatype VARCHAR, value DOUBLE, uom VARCHAR,
        currency VARCHAR, source_adsh VARCHAR, source_tag VARCHAR, alias_rank INTEGER, source_filed DATE,
        source_form VARCHAR, n_candidates BIGINT, n_sources BIGINT, n_distinct_values BIGINT, is_restated BOOLEAN,
        status VARCHAR, resolution_reason VARCHAR)""",
    "restatements": """CREATE TABLE restatements (cik BIGINT, tag VARCHAR, period_end DATE, qtrs INTEGER, uom VARCHAR,
        adsh VARCHAR, form VARCHAR, filed DATE, value DOUBLE, is_current_period BOOLEAN, version VARCHAR,
        is_authoritative BOOLEAN, authoritative_value DOUBLE, authoritative_adsh VARCHAR, authoritative_form VARCHAR,
        authoritative_filed DATE, n_versions BIGINT, delta DOUBLE, rel_diff DOUBLE, group_max_rel_diff DOUBLE,
        classification VARCHAR)""",
    "fact_ratios": """CREATE TABLE fact_ratios (cik BIGINT, period_end DATE, basis VARCHAR, fiscal_year INTEGER,
        fiscal_quarter INTEGER, ratio VARCHAR, value DOUBLE, status VARCHAR, reason VARCHAR, inputs_json VARCHAR,
        source_adshs VARCHAR[], currency VARCHAR)""",
}


def create_schema(con: duckdb.DuckDBPyConnection) -> None:
    for ddl in DDL.values():
        con.execute(ddl)
    aliases.create_alias_table(con)
    aliases.create_sic_table(con)


# ------------------------------------------------------------------ row helpers

def add_company(con, cik=1, name="TEST CO", sic=3571, fye_month=12, is_financial=False, sector="Manufacturing",
                industry="Computers"):
    con.execute("INSERT INTO dim_company VALUES (?, ?, ?, ?, ?, 35, ?, 'DE', 'US', 'CA', 'US', "
                "'1-LAF', ?, ?, false, DATE '2024-01-01', DATE '2026-01-01', 8, 8, 2, 6)",
                [cik, name, sic, sector, industry, is_financial, f"{fye_month:02d}31", fye_month])


def add_filing(con, adsh, cik=1, form="10-K", period="2024-12-31", filed="2025-02-15", fy=2024, fp="FY",
               in_scope=True, quarter="2025q1"):
    is_amend = form.endswith("/A")
    rt = "annual" if form.startswith("10-K") else ("quarterly" if form.startswith("10-Q") else "other")
    con.execute("INSERT INTO dim_filing VALUES (?, ?, 'TEST CO', 3571, ?, ?, ?, ?, ?, NULL, false, true, 1, NULL, '1231', "
                "'1-LAF', 0, 'DE', 'US', 'CA', 'US', ?, ?, ?, ?, '')",
                [adsh, cik, form, period, fy, fp, filed, quarter, is_amend, in_scope, rt])


def add_tag(con, tag, datatype="monetary", iord="I", version="us-gaap/2024", custom=False):
    con.execute("INSERT INTO dim_tag VALUES (?, ?, ?, ?, false, ?, ?, 'C', ?, '')",
                [tag, version, version.split("/")[0], custom, datatype, iord, tag])


def add_fact(con, adsh, tag, value, period_end="2024-12-31", qtrs=0, uom="USD", cik=1, version="us-gaap/2024",
             segments=None, coreg=None, form="10-K", filed="2025-02-15", filing_period=None, fiscal_year=None,
             fiscal_quarter=None, quarter="2025q1"):
    filing_period = filing_period or period_end
    fy = fiscal_year or int(period_end[:4])
    con.execute("INSERT INTO fact_financial_facts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [adsh, cik, tag, version, version.split("/")[0], version == adsh,
                 period_end.replace("-", "") + "-" + str(qtrs), period_end, qtrs, uom, value, segments, coreg,
                 form, filed, "annual" if form.startswith("10-K") else "quarterly", filing_period,
                 segments is None and coreg is None, period_end == filing_period, fy, fiscal_quarter, quarter])


def add_norm(con, metric, value, period_end="2024-12-31", qtrs=0, cik=1, adsh="0000000001-25-000001",
             tag=None, status="reported", datatype="monetary", currency="USD", fiscal_year=None,
             fiscal_quarter=None, filed="2025-02-15", form="10-K", is_restated=False):
    fy = fiscal_year or int(period_end[:4])
    con.execute("INSERT INTO fact_normalized VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, 1, 1, 1, ?, ?, 'test')",
                [cik, period_end, period_end.replace("-", "") + "-" + str(qtrs), qtrs, fy, fiscal_quarter, metric,
                 datatype, value, currency if datatype != "shares" else "shares", currency, adsh, tag or metric,
                 filed, form, is_restated, status])


def add_ratio(con, cik, ratio, value, period_end="2024-12-31", basis="FY", fiscal_year=None, status=None,
              reason=None, adshs=None):
    fy = fiscal_year or int(period_end[:4])
    status = status or ("ok" if value is not None else "null")
    con.execute("INSERT INTO fact_ratios VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, '{}', ?, 'USD')",
                [cik, period_end, basis, fy, ratio, value, status, reason, adshs or [f"{cik:010d}-25-000001"]])
