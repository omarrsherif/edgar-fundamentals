-- id: R01
-- name: balance_sheet_identity
-- category: identity
-- severity: error
-- unit: company balance-sheet date with reported total assets or total liabilities-and-equity
-- description: Total assets must equal LiabilitiesAndStockholdersEquity within 0.1% (floor USD 1,000). Skipped when only one side is reported.
SELECT
  CASE WHEN total_assets IS NULL OR liabilities_and_equity IS NULL THEN 'skip'
       WHEN abs(total_assets - liabilities_and_equity)
            <= greatest(${face_total_rel} * greatest(abs(total_assets), abs(liabilities_and_equity)), ${abs_floor}) THEN 'pass'
       ELSE 'fail' END AS status,
  cik, adsh, period_end, qtrs, 'Assets' AS tag,
  total_assets AS observed, liabilities_and_equity AS expected,
  total_assets - liabilities_and_equity AS diff,
  'Assets != LiabilitiesAndStockholdersEquity' AS message
FROM dq_wide
WHERE qtrs = 0 AND (total_assets IS NOT NULL OR liabilities_and_equity IS NOT NULL)
