-- id: R22
-- name: value_magnitude_plausibility
-- category: plausibility
-- severity: error
-- unit: consolidated monetary / share / per-share fact
-- description: Values beyond physically plausible magnitudes (USD > 1e14, shares > 1e13, per-share > 1e5) indicate scaling errors in the filing.
WITH f AS (
  SELECT f.cik, f.adsh, f.period_end, f.qtrs, f.tag, f.uom, f.value, t.datatype
  FROM fact_financial_facts f
  JOIN dim_tag t ON t.tag = f.tag AND t.version = f.version
  WHERE f.is_consolidated AND t.datatype IN ('monetary', 'shares', 'perShare')
),
c AS (
  SELECT *,
    CASE WHEN datatype = 'monetary' AND uom = 'USD' THEN abs(value) > ${magnitude_usd_max}
         WHEN datatype = 'shares' THEN abs(value) > ${magnitude_shares_max}
         WHEN datatype = 'perShare' THEN abs(value) > ${magnitude_eps_max}
         ELSE FALSE END AS bad
  FROM f
)
SELECT 'pass' AS status, count(*) AS n, NULL::BIGINT AS cik, NULL::VARCHAR AS adsh, NULL::DATE AS period_end,
       NULL::INTEGER AS qtrs, NULL::VARCHAR AS tag, NULL::DOUBLE AS observed, NULL::DOUBLE AS expected,
       NULL::DOUBLE AS diff, NULL::VARCHAR AS message
FROM c WHERE NOT bad
UNION ALL
SELECT 'fail', 1, cik, adsh, period_end, qtrs, tag, value, NULL, NULL,
       'implausible magnitude for ' || datatype || ' value in ' || uom
FROM c WHERE bad
