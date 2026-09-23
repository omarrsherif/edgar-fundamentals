-- id: R21
-- name: instant_duration_consistency
-- category: referential
-- severity: error
-- unit: modelled fact whose tag declares an instant/duration period type
-- description: Instant tags (iord = I, balance-sheet items) must be reported with qtrs = 0. Duration tags with qtrs = 0 are skipped: FSDS rounds durations shorter than ~45 days (e.g. a share issuance on a single date) to zero quarters, so they cannot be judged.
WITH f AS (
  SELECT f.cik, f.adsh, f.period_end, f.qtrs, f.tag, t.iord
  FROM fact_financial_facts f
  JOIN dim_tag t ON t.tag = f.tag AND t.version = f.version
  WHERE t.iord IN ('I', 'D')
)
SELECT 'pass' AS status, count(*) AS n, NULL::BIGINT AS cik, NULL::VARCHAR AS adsh, NULL::DATE AS period_end,
       NULL::INTEGER AS qtrs, NULL::VARCHAR AS tag, NULL::DOUBLE AS observed, NULL::DOUBLE AS expected,
       NULL::DOUBLE AS diff, NULL::VARCHAR AS message
FROM f WHERE (iord = 'I' AND qtrs = 0) OR (iord = 'D' AND qtrs > 0)
UNION ALL
SELECT 'skip', count(*), NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 'duration tag with sub-quarter duration (qtrs rounded to 0)'
FROM f WHERE iord = 'D' AND qtrs = 0
UNION ALL
SELECT 'fail', 1, cik, adsh, period_end, qtrs, tag, qtrs, 0, qtrs, 'instant tag reported with a duration of ' || qtrs || ' quarters'
FROM f WHERE iord = 'I' AND qtrs > 0
