-- id: R07
-- name: period_continuity
-- category: continuity
-- severity: error
-- unit: year-to-date flow value (company, metric, period end) for revenue, cost of revenue, operating income, net income, operating cash flow
-- description: A year-to-date value must equal the previous year-to-date value plus the quarter: YTD(n) = YTD(n-1) + Q(n), within 0.5%. Skipped when either component is not reported (e.g. Q4 is almost never filed as a standalone quarter).
WITH m AS (
  SELECT cik, period_end, qtrs, metric, value, source_adsh
  FROM fact_normalized
  WHERE metric IN ('revenue', 'cost_of_revenue', 'operating_income', 'net_income', 'operating_cash_flow')
    AND qtrs IN (1, 2, 3, 4)
),
pairs AS (
  SELECT y.cik, y.period_end, y.qtrs, y.metric, y.value AS ytd_value, y.source_adsh,
         p.value AS prior_ytd, q.value AS quarter_value
  FROM m y
  LEFT JOIN m p ON p.cik = y.cik AND p.metric = y.metric AND p.qtrs = y.qtrs - 1
               AND p.period_end = last_day((y.period_end - to_months(3))::DATE)
  LEFT JOIN m q ON q.cik = y.cik AND q.metric = y.metric AND q.qtrs = 1 AND q.period_end = y.period_end
  WHERE y.qtrs IN (2, 3, 4)
)
SELECT
  CASE WHEN prior_ytd IS NULL OR quarter_value IS NULL THEN 'skip'
       WHEN abs(ytd_value - (prior_ytd + quarter_value))
            <= greatest(${multi_term_rel} * greatest(abs(ytd_value), abs(prior_ytd + quarter_value)), ${abs_floor}) THEN 'pass'
       ELSE 'fail' END AS status,
  cik, source_adsh AS adsh, period_end, qtrs, metric AS tag,
  ytd_value AS observed, prior_ytd + quarter_value AS expected,
  ytd_value - (prior_ytd + quarter_value) AS diff,
  'YTD(' || qtrs || ') != YTD(' || (qtrs - 1) || ') + quarter for ' || metric AS message
FROM pairs
