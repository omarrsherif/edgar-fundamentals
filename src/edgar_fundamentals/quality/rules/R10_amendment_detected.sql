-- id: R10
-- name: amendment_detected
-- category: restatement
-- severity: info
-- unit: original (non-amended) in-scope filing
-- description: An original 10-K/10-Q that was later superseded by a 10-K/A or 10-Q/A for the same company and period. Computed from the data rather than the stale prevrpt flag.
WITH f AS (SELECT * FROM dim_filing WHERE in_scope AND period IS NOT NULL),
orig AS (SELECT * FROM f WHERE NOT is_amendment),
amend AS (
  SELECT cik, replace(form, '/A', '') AS base_form, period,
         arg_max(adsh, filed) AS amend_adsh, max(filed) AS amend_filed
  FROM f WHERE is_amendment GROUP BY ALL
)
SELECT
  CASE WHEN a.amend_adsh IS NULL THEN 'pass' ELSE 'fail' END AS status,
  o.cik, o.adsh, o.period AS period_end, NULL::INTEGER AS qtrs, o.form AS tag,
  NULL::DOUBLE AS observed, NULL::DOUBLE AS expected, NULL::DOUBLE AS diff,
  'superseded by ' || a.amend_adsh || ' filed ' || a.amend_filed AS message
FROM orig o
LEFT JOIN amend a ON a.cik = o.cik AND a.base_form = o.form AND a.period = o.period
