-- id: R18
-- name: eps_consistency
-- category: plausibility
-- severity: error
-- unit: company flow period with reported basic EPS
-- description: Net income / weighted-average basic shares must agree with reported basic EPS within 5% (floor 0.01). Catches share counts or EPS reported at the wrong scale. Skipped when net income or basic shares are missing or zero.
SELECT
  CASE WHEN net_income IS NULL OR weighted_shares_basic IS NULL OR weighted_shares_basic = 0 THEN 'skip'
       WHEN abs(net_income / weighted_shares_basic - eps_basic) <= greatest(${eps_rel} * abs(eps_basic), 0.01) THEN 'pass'
       ELSE 'fail' END AS status,
  cik, adsh, period_end, qtrs, 'EarningsPerShareBasic' AS tag,
  net_income / nullif(weighted_shares_basic, 0) AS observed, eps_basic AS expected,
  net_income / nullif(weighted_shares_basic, 0) - eps_basic AS diff,
  'NetIncome / weighted basic shares != EPS basic' AS message
FROM dq_wide
WHERE qtrs > 0 AND eps_basic IS NOT NULL
