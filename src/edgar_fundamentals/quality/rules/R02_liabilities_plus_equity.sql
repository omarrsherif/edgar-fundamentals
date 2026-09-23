-- id: R02
-- name: liabilities_plus_equity
-- category: identity
-- severity: error
-- unit: company balance-sheet date with reported liabilities-and-equity
-- description: Reported total liabilities + total equity (incl. NCI) + temporary equity must equal LiabilitiesAndStockholdersEquity within 0.5%. Skipped when Liabilities is not reported (derived values would be tautological).
WITH w AS (
  SELECT *,
    total_liabilities + equity_incl_nci + coalesce(temporary_equity, 0) AS observed_sum
  FROM dq_wide
  WHERE qtrs = 0 AND liabilities_and_equity IS NOT NULL
)
SELECT
  CASE WHEN total_liabilities IS NULL OR total_liabilities_status <> 'reported' OR equity_incl_nci IS NULL THEN 'skip'
       WHEN abs(observed_sum - liabilities_and_equity)
            <= greatest(${multi_term_rel} * greatest(abs(observed_sum), abs(liabilities_and_equity)), ${abs_floor}) THEN 'pass'
       ELSE 'fail' END AS status,
  cik, adsh, period_end, qtrs, 'Liabilities' AS tag,
  observed_sum AS observed, liabilities_and_equity AS expected,
  observed_sum - liabilities_and_equity AS diff,
  'Liabilities + equity (incl. NCI) + temporary equity != LiabilitiesAndStockholdersEquity' AS message
FROM w
