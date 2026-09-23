-- id: R06
-- name: current_liabilities_le_total_liabilities
-- category: plausibility
-- severity: error
-- unit: company balance-sheet date with total liabilities (reported or derived)
-- description: Current liabilities cannot exceed total liabilities (0.1% tolerance). Skipped when no current liabilities are reported.
SELECT
  CASE WHEN current_liabilities IS NULL THEN 'skip'
       WHEN current_liabilities <= total_liabilities + greatest(${face_total_rel} * abs(total_liabilities), ${abs_floor}) THEN 'pass'
       ELSE 'fail' END AS status,
  cik, adsh, period_end, qtrs, 'LiabilitiesCurrent' AS tag,
  current_liabilities AS observed, total_liabilities AS expected, current_liabilities - total_liabilities AS diff,
  'LiabilitiesCurrent > Liabilities (' || total_liabilities_status || ')' AS message
FROM dq_wide
WHERE qtrs = 0 AND total_liabilities IS NOT NULL
