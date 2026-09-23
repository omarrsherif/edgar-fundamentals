-- id: R16
-- name: gross_profit_consistency
-- category: identity
-- severity: error
-- unit: company flow period with a reported GrossProfit
-- description: Revenue - cost of revenue must equal reported gross profit within 0.5%. Skipped when revenue or cost of revenue is not reported.
SELECT
  CASE WHEN revenue IS NULL OR cost_of_revenue IS NULL THEN 'skip'
       WHEN abs((revenue - cost_of_revenue) - gross_profit)
            <= greatest(${multi_term_rel} * greatest(abs(revenue - cost_of_revenue), abs(gross_profit)), ${abs_floor}) THEN 'pass'
       ELSE 'fail' END AS status,
  cik, adsh, period_end, qtrs, 'GrossProfit' AS tag,
  revenue - cost_of_revenue AS observed, gross_profit AS expected,
  (revenue - cost_of_revenue) - gross_profit AS diff,
  'Revenue - CostOfRevenue != GrossProfit' AS message
FROM dq_wide
WHERE qtrs > 0 AND gross_profit IS NOT NULL AND gross_profit_status = 'reported'
