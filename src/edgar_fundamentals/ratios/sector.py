"""Precomputed sector aggregates for the dashboard's Sector tab (built by `edgar-fundamentals ratios`).

sector_ratio_latest  one row per (cik, ratio): the company's latest FY value with a non-null result, its
                     sector, and the percentile rank within the sector = share of sector companies whose
                     latest value is strictly lower (ties count in the denominator, not the numerator).
                     This is exactly what the dashboard used to compute in pandas per request:
                     latest = df.sort_values("period_end").groupby("cik").tail(1); (latest.value < v).mean()
sector_ratio_yearly  median FY value per (sector, ratio, fiscal_year) over all FY rows with a value, as the
                     dashboard used to compute with groupby("fiscal_year")["value"].median().

Both tables are as fresh as fact_ratios: they are rebuilt in the same command and are stale between builds.
"""
from __future__ import annotations

import time

import duckdb

from edgar_fundamentals.log import get_logger

log = get_logger("edgar.ratios.sector")

SECTOR_LATEST_SQL = """
CREATE OR REPLACE TABLE sector_ratio_latest AS
WITH fy AS (
    SELECT r.cik, c.sector, r.ratio, r.fiscal_year, r.period_end, r.value, r.source_adshs
    FROM fact_ratios r
    JOIN dim_company c USING (cik)
    WHERE r.basis = 'FY' AND r.value IS NOT NULL
),
latest AS (
    SELECT * FROM fy
    QUALIFY row_number() OVER (PARTITION BY cik, ratio ORDER BY period_end DESC) = 1
),
ranked AS (
    SELECT cik, sector, ratio, 'FY' AS basis, fiscal_year, period_end, value, source_adshs,
           count(*) OVER (PARTITION BY sector, ratio) AS n_companies,
           rank() OVER (PARTITION BY sector, ratio ORDER BY value) - 1 AS n_lower
    FROM latest
)
SELECT *, CAST(n_lower AS DOUBLE) / n_companies AS pct_rank
FROM ranked
ORDER BY sector, ratio, cik
"""

SECTOR_YEARLY_SQL = """
CREATE OR REPLACE TABLE sector_ratio_yearly AS
SELECT c.sector, r.ratio, r.fiscal_year,
       median(r.value) AS median_value,
       count(*) AS n_rows,
       count(DISTINCT r.cik) AS n_companies
FROM fact_ratios r
JOIN dim_company c USING (cik)
WHERE r.basis = 'FY' AND r.value IS NOT NULL
GROUP BY ALL
ORDER BY sector, ratio, fiscal_year
"""


def build_sector_tables(con: duckdb.DuckDBPyConnection) -> dict:
    t0 = time.perf_counter()
    con.execute(SECTOR_LATEST_SQL)
    n_latest = con.execute("SELECT count(*) FROM sector_ratio_latest").fetchone()[0]
    con.execute(SECTOR_YEARLY_SQL)
    n_yearly = con.execute("SELECT count(*) FROM sector_ratio_yearly").fetchone()[0]
    seconds = time.perf_counter() - t0
    log.info("sector_ratio_latest: %s rows, sector_ratio_yearly: %s rows (%.2fs)", f"{n_latest:,}", f"{n_yearly:,}", seconds)
    return {"sector_ratio_latest_rows": n_latest, "sector_ratio_yearly_rows": n_yearly, "seconds": seconds}
