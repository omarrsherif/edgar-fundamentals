-- id: R11
-- name: duplicate_filing
-- category: duplicate
-- severity: warn
-- unit: original (non-amended) in-scope filing
-- description: The same company filed the same form for the same period more than once without marking it as an amendment.
WITH f AS (
  SELECT cik, form, period, adsh, filed FROM dim_filing
  WHERE in_scope AND NOT is_amendment AND period IS NOT NULL
),
g AS (
  SELECT cik, form, period, count(*) AS n, string_agg(adsh, ', ' ORDER BY filed) AS adshs
  FROM f GROUP BY ALL
)
SELECT
  CASE WHEN g.n > 1 THEN 'fail' ELSE 'pass' END AS status,
  f.cik, f.adsh, f.period AS period_end, NULL::INTEGER AS qtrs, f.form AS tag,
  g.n AS observed, 1 AS expected, g.n - 1 AS diff,
  'same form and period filed as: ' || g.adshs AS message
FROM f JOIN g USING (cik, form, period)
