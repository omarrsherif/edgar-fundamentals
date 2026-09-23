-- id: R17
-- name: cash_flow_identity
-- category: identity
-- severity: error
-- unit: company flow period with reported operating cash flow
-- description: Operating + investing + financing cash flow (+ FX effect) must equal the reported change in cash within 0.5%, pairing the including-FX or excluding-FX variant of the change-in-cash tag. Skipped when a component or the change-in-cash total is not reported.
WITH w AS (
  SELECT *,
    CASE WHEN cash_change_incl_fx IS NOT NULL THEN cash_change_incl_fx ELSE cash_change_excl_fx END AS expected_change,
    operating_cash_flow + investing_cash_flow + financing_cash_flow
      + CASE WHEN cash_change_incl_fx IS NOT NULL THEN coalesce(fx_effect, 0) ELSE 0 END AS observed_change,
    CASE WHEN cash_change_incl_fx IS NOT NULL THEN 'incl_fx' ELSE 'excl_fx' END AS variant
  FROM dq_wide
  WHERE qtrs > 0 AND operating_cash_flow IS NOT NULL
)
SELECT
  CASE WHEN investing_cash_flow IS NULL OR financing_cash_flow IS NULL OR expected_change IS NULL THEN 'skip'
       WHEN abs(observed_change - expected_change)
            <= greatest(${multi_term_rel} * greatest(abs(observed_change), abs(expected_change)), ${abs_floor}) THEN 'pass'
       ELSE 'fail' END AS status,
  cik, adsh, period_end, qtrs, 'NetCashProvidedByUsedInOperatingActivities' AS tag,
  observed_change AS observed, expected_change AS expected, observed_change - expected_change AS diff,
  'op + inv + fin (+ fx) != change in cash (' || variant || ')' AS message
FROM w
