-- id: R04
-- name: revenue_nonnegative
-- category: sign
-- severity: warn
-- unit: normalized revenue value (company, period, duration)
-- description: Revenue should not be negative. Warn-level because RevenuesNetOfInterestExpense can legitimately be negative for financial firms.
SELECT
  CASE WHEN value < 0 THEN 'fail' ELSE 'pass' END AS status,
  cik, source_adsh AS adsh, period_end, qtrs, source_tag AS tag,
  value AS observed, 0 AS expected, value AS diff,
  'negative revenue (' || source_tag || ')' AS message
FROM fact_normalized
WHERE metric = 'revenue'
