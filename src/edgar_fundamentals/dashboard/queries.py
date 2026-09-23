"""The five dashboard queries. The benchmark runs exactly these, with these default parameters."""
from __future__ import annotations

COMPANY_SEARCH = """
SELECT cik, name, sic, sector, industry, n_in_scope_filings, last_filed
FROM dim_company
WHERE name ILIKE '%' || $1 || '%' OR CAST(cik AS VARCHAR) = $1
ORDER BY (name ILIKE $1 || '%') DESC, (CAST(cik AS VARCHAR) = $1) DESC, n_in_scope_filings DESC, length(name), name
LIMIT 25
"""

COMPANY_RATIO_TREND = """
SELECT period_end, basis, fiscal_year, fiscal_quarter, ratio, value, status, reason, source_adshs, inputs_json, currency
FROM fact_ratios
WHERE cik = $1
ORDER BY period_end, ratio
"""

MULTI_COMPANY_COMPARE = """
SELECT r.cik, c.name, r.period_end, r.basis, r.fiscal_year, r.ratio, r.value, r.status, r.source_adshs
FROM fact_ratios r
JOIN dim_company c USING (cik)
WHERE list_contains($1::BIGINT[], r.cik) AND r.basis = $2
ORDER BY r.period_end, r.cik, r.ratio
"""

# Original (pre-optimization) sector query: full FY history for every company in the sector, including the
# source_adshs list column; the dashboard then reduced it in pandas to the latest value per company and
# computed the percentile per request. Kept for the equivalence tests (tests/test_optimization_equivalence.py).
SECTOR_PERCENTILE_V0 = """
SELECT r.cik, c.name, c.industry, r.ratio, r.fiscal_year, r.period_end, r.value, r.source_adshs
FROM fact_ratios r
JOIN dim_company c USING (cik)
WHERE c.sector = $1 AND r.basis = 'FY' AND r.value IS NOT NULL
ORDER BY r.ratio, r.period_end
"""

# Optimized: one row per (company, ratio) from the precomputed sector_ratio_latest table (built by
# `edgar-fundamentals ratios`), percentile rank included; no list column.
SECTOR_PERCENTILE = """
SELECT s.cik, c.name, s.ratio, s.fiscal_year, s.period_end, s.value, s.n_companies, s.pct_rank
FROM sector_ratio_latest s
JOIN dim_company c USING (cik)
WHERE s.sector = $1
"""

SECTOR_MEDIAN_TREND = """
SELECT ratio, fiscal_year, median_value, n_companies
FROM sector_ratio_yearly WHERE sector = $1 ORDER BY ratio, fiscal_year
"""

SECTOR_FOCUS_SOURCES = "SELECT ratio, source_adshs FROM sector_ratio_latest WHERE cik = $1"

DQ_SUMMARY = """
SELECT s.*,
       (SELECT count(*) FROM restatements WHERE classification = 'restatement' AND is_authoritative) AS restatement_groups
FROM dq_summary s
ORDER BY s.rule_id
"""

# Default parameters used by the benchmark (Apple, Microsoft, Alphabet-sized companies; the largest sector).
BENCH_QUERIES: dict[str, tuple[str, list]] = {
    "company_search": (COMPANY_SEARCH, ["micro"]),
    "company_ratio_trend": (COMPANY_RATIO_TREND, [320193]),
    "multi_company_compare": (MULTI_COMPANY_COMPARE, [[320193, 789019, 1652044, 1018724, 1045810], "FY"]),
    "sector_percentile": (SECTOR_PERCENTILE, ["Manufacturing"]),
    "dq_summary": (DQ_SUMMARY, []),
}

# Supporting lookups used by the UI but not benchmarked.
SECTORS = "SELECT sector, count(*) AS n FROM dim_company GROUP BY sector ORDER BY n DESC"
COMPANY_FACTS = """
SELECT metric, period_end, qtrs, value, currency, source_tag, source_adsh, status, is_restated, resolution_reason
FROM fact_normalized WHERE cik = $1 ORDER BY period_end DESC, qtrs, metric
"""
COMPANY_RESTATEMENTS = """
SELECT tag, period_end, qtrs, uom, adsh, form, filed, value, is_authoritative, authoritative_value, authoritative_adsh,
       rel_diff, classification
FROM restatements WHERE cik = $1 AND classification = 'restatement'
ORDER BY rel_diff DESC, period_end DESC LIMIT 200
"""
TOP_RESTATEMENTS = """
SELECT r.cik, c.name, r.tag, r.period_end, r.qtrs, r.uom, r.adsh AS earlier_adsh, r.filed AS earlier_filed,
       r.value AS earlier_value, r.authoritative_adsh, r.authoritative_filed, r.authoritative_value, r.rel_diff
FROM restatements r JOIN dim_company c USING (cik)
WHERE r.classification = 'restatement' AND NOT r.is_authoritative AND abs(r.authoritative_value) >= 1e6
ORDER BY r.rel_diff DESC, r.authoritative_filed DESC LIMIT 300
"""
DQ_FAILURES = """
SELECT r.rule_id, r.rule_name, r.severity, r.cik, c.name, r.adsh, r.period_end, r.qtrs, r.tag, r.observed, r.expected,
       r.diff, r.message
FROM dq_results r LEFT JOIN dim_company c USING (cik)
WHERE r.rule_name = $1
ORDER BY abs(r.diff) DESC NULLS LAST LIMIT 500
"""
COMPANY_DQ = """
SELECT rule_id, rule_name, severity, adsh, period_end, qtrs, tag, observed, expected, diff, message
FROM dq_results WHERE cik = $1 ORDER BY rule_id, period_end DESC LIMIT 500
"""
