-- id: R08
-- name: quarters_sum_to_annual
-- category: continuity
-- severity: error
-- unit: (company, metric, fiscal year) with a reported annual value
-- description: Where all four standalone quarters are reported, they must sum to the annual value within 0.5%. Coverage is low because Q4 is rarely filed as a standalone quarter.
WITH m AS (
  SELECT cik, metric, fiscal_year, fiscal_quarter, qtrs, period_end, value, source_adsh
  FROM fact_normalized
  WHERE metric IN ('revenue', 'cost_of_revenue', 'operating_income', 'net_income', 'operating_cash_flow')
    AND fiscal_quarter IS NOT NULL
),
annual AS (
  SELECT cik, metric, fiscal_year, period_end, value AS annual_value, source_adsh
  FROM m WHERE qtrs = 4 AND fiscal_quarter = 4
),
q AS (
  SELECT cik, metric, fiscal_year, count(DISTINCT fiscal_quarter) AS n_q, sum(value) AS q_sum
  FROM m WHERE qtrs = 1
  GROUP BY ALL
)
SELECT
  CASE WHEN q.n_q IS NULL OR q.n_q < 4 THEN 'skip'
       WHEN abs(a.annual_value - q.q_sum)
            <= greatest(${multi_term_rel} * greatest(abs(a.annual_value), abs(q.q_sum)), ${abs_floor}) THEN 'pass'
       ELSE 'fail' END AS status,
  a.cik, a.source_adsh AS adsh, a.period_end, 4 AS qtrs, a.metric AS tag,
  a.annual_value AS observed, q.q_sum AS expected, a.annual_value - q.q_sum AS diff,
  'sum of Q1..Q4 != annual for ' || a.metric || ' FY' || a.fiscal_year AS message
FROM annual a LEFT JOIN q USING (cik, metric, fiscal_year)
