-- id: R14
-- name: missing_mandatory_tags
-- category: completeness
-- severity: error
-- unit: 10-K / 10-Q filing that carries a balance sheet
-- description: Every primary filing must report the mandatory canonical metrics for its form (config/mandatory_tags.yaml) after alias resolution; revenue is not required for financial-sector SICs, and only required when the filing reports cost of revenue or gross profit (pre-revenue and investment companies have no revenue line).
WITH bs AS (
  SELECT DISTINCT cik, period_end FROM fact_normalized WHERE qtrs = 0 AND datatype = 'monetary'
),
f AS (
  SELECT d.adsh, d.cik, d.period, d.report_type, d.form, c.is_financial
  FROM dim_filing d
  JOIN dim_company c USING (cik)
  JOIN bs ON bs.cik = d.cik AND bs.period_end = d.period
  WHERE d.in_scope AND d.period IS NOT NULL AND d.report_type IN ('annual', 'quarterly')
),
cond_ok AS (
  SELECT DISTINCT c.metric, n.cik, n.period_end
  FROM fact_normalized n JOIN mandatory_conditional c ON c.requires_any_of = n.metric
  WHERE n.qtrs > 0
),
req AS (
  SELECT f.*, m.metric
  FROM f JOIN mandatory_metrics m USING (report_type)
  LEFT JOIN cond_ok k ON k.metric = m.metric AND k.cik = f.cik AND k.period_end = f.period
  WHERE NOT (f.is_financial AND m.metric IN (SELECT metric FROM mandatory_financial_exempt))
    AND (m.metric NOT IN (SELECT metric FROM mandatory_conditional) OR k.metric IS NOT NULL)
),
present AS (
  SELECT r.adsh, r.metric, bool_or(n.value IS NOT NULL) AS has
  FROM req r
  LEFT JOIN fact_normalized n
    ON n.cik = r.cik AND n.metric = r.metric AND n.period_end = r.period
   AND (n.qtrs = 0 OR (r.report_type = 'annual' AND n.qtrs = 4) OR (r.report_type = 'quarterly' AND n.qtrs IN (1, 2, 3)))
  GROUP BY ALL
),
per_filing AS (
  SELECT adsh,
         string_agg(metric, ', ' ORDER BY metric) FILTER (WHERE NOT has) AS missing,
         count(*) FILTER (WHERE NOT has) AS n_missing
  FROM present GROUP BY adsh
)
SELECT
  CASE WHEN n_missing > 0 THEN 'fail' ELSE 'pass' END AS status,
  f.cik, f.adsh, f.period AS period_end, NULL::INTEGER AS qtrs,
  split_part(missing, ', ', 1) AS tag,
  n_missing AS observed, 0 AS expected, n_missing AS diff,
  f.form || ' missing: ' || missing AS message
FROM f JOIN per_filing USING (adsh)
