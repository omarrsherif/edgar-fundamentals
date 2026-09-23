-- filing_currency: the dominant monetary unit of each filing (mode of uom over consolidated monetary facts).
CREATE OR REPLACE TABLE filing_currency AS
SELECT adsh, uom AS currency, n AS n_monetary_facts
FROM (
  SELECT f.adsh, f.uom, count(*) AS n
  FROM fact_financial_facts f
  JOIN dim_tag t ON t.tag = f.tag AND t.version = f.version
  WHERE f.is_consolidated AND t.datatype = 'monetary'
  GROUP BY ALL
)
QUALIFY row_number() OVER (PARTITION BY adsh ORDER BY n DESC, uom) = 1;

-- fact_normalized: one value per (company, period end, duration, canonical metric), chosen by alias
-- priority from config/aliases.yaml, then by latest filing. Derived rows are appended by
-- warehouse/aliases.py::apply_derivations.
CREATE OR REPLACE TABLE fact_normalized AS
WITH cand AS (
  SELECT
    f.cik, f.period_end, f.period_key, f.qtrs, f.fiscal_year, f.fiscal_quarter,
    a.canonical_metric, a.datatype,
    f.value, f.uom, f.tag, a.priority, f.adsh, f.filed, f.form,
    coalesce(fc.currency, 'USD') AS currency
  FROM fact_financial_facts f
  JOIN alias_map a ON a.tag = f.tag AND (a.taxonomy IS NULL OR a.taxonomy = f.taxonomy)
  JOIN dim_tag t ON t.tag = f.tag AND t.version = f.version
  LEFT JOIN filing_currency fc ON fc.adsh = f.adsh
  WHERE f.is_consolidated AND NOT f.is_custom_tag AND t.datatype = a.datatype
    AND (
      (a.datatype = 'monetary' AND f.uom = coalesce(fc.currency, 'USD'))
      OR (a.datatype = 'shares' AND f.uom = 'shares')
      OR (a.datatype = 'perShare' AND f.uom = coalesce(fc.currency, 'USD'))
      OR (a.datatype = 'pure')
    )
),
ranked AS (
  SELECT *,
    count(*) OVER w AS n_candidates,
    count(DISTINCT adsh) OVER w AS n_sources,
    count(DISTINCT value) OVER w AS n_distinct_values,
    row_number() OVER (PARTITION BY cik, period_end, qtrs, canonical_metric
                       ORDER BY priority, filed DESC, (form LIKE '%/A') DESC, adsh DESC, tag) AS rn
  FROM cand
  WINDOW w AS (PARTITION BY cik, period_end, qtrs, canonical_metric)
)
SELECT
  r.cik, r.period_end, r.period_key, r.qtrs, r.fiscal_year, r.fiscal_quarter,
  r.canonical_metric AS metric, r.datatype,
  r.value, r.uom, r.currency,
  r.adsh AS source_adsh, r.tag AS source_tag, r.priority AS alias_rank,
  r.filed AS source_filed, r.form AS source_form,
  r.n_candidates, r.n_sources, r.n_distinct_values,
  coalesce(rs.classification = 'restatement', false) AS is_restated,
  'reported' AS status,
  'alias_priority=' || r.priority
    || ';authoritative=' || CASE WHEN r.n_sources > 1 THEN 'latest_filed' ELSE 'single_source' END
    || CASE WHEN rs.classification = 'restatement' THEN ';restated'
            WHEN rs.classification = 'rounding_diff' THEN ';rounding_diff' ELSE '' END AS resolution_reason
FROM ranked r
LEFT JOIN (SELECT DISTINCT cik, tag, period_end, qtrs, uom, classification FROM restatements) rs
  ON rs.cik = r.cik AND rs.tag = r.tag AND rs.period_end = r.period_end AND rs.qtrs = r.qtrs AND rs.uom = r.uom
WHERE r.rn = 1;
