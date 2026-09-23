-- id: R19
-- name: fiscal_period_validity
-- category: referential
-- severity: error
-- unit: in-scope filing
-- description: Submission metadata must be coherent: period and filed present, fp in the allowed set, fy within one year of the period, period not after the filing date, and 10-K forms tagged fp = FY.
SELECT
  CASE WHEN problems = '' THEN 'pass' ELSE 'fail' END AS status,
  cik, adsh, period AS period_end, NULL::INTEGER AS qtrs, form AS tag,
  NULL::DOUBLE AS observed, NULL::DOUBLE AS expected, NULL::DOUBLE AS diff,
  problems AS message
FROM (
  SELECT *,
    concat_ws('; ',
      CASE WHEN period IS NULL THEN 'period missing' END,
      CASE WHEN filed IS NULL THEN 'filed missing' END,
      CASE WHEN fp_reported IS NULL OR fp_reported NOT IN (${allowed_fp})
           THEN 'fp=' || coalesce(fp_reported, 'NULL') || ' not allowed' END,
      CASE WHEN fy_reported IS NULL OR abs(fy_reported - year(period)) > 1
           THEN 'fy=' || coalesce(fy_reported::VARCHAR, 'NULL') || ' inconsistent with period ' || coalesce(period::VARCHAR, 'NULL') END,
      CASE WHEN period > filed THEN 'period after filing date' END,
      CASE WHEN report_type = 'annual' AND fp_reported <> 'FY' THEN '10-K with fp=' || fp_reported END
    ) AS problems
  FROM dim_filing WHERE in_scope
)
