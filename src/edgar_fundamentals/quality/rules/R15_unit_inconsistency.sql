-- id: R15
-- name: unit_inconsistency
-- category: unit
-- severity: error
-- unit: consolidated fact with a typed tag (monetary / shares / perShare / pure)
-- description: The unit of measure must match the tag's datatype (monetary -> ISO currency, shares -> shares, perShare -> ISO currency (FSDS stores per-share units as the bare currency), pure -> pure); additionally a monetary tag must not be reported in two currencies inside one filing.
WITH f AS (
  SELECT f.cik, f.adsh, f.period_end, f.qtrs, f.tag, f.uom, t.datatype
  FROM fact_financial_facts f
  JOIN dim_tag t ON t.tag = f.tag AND t.version = f.version
  WHERE f.is_consolidated AND NOT f.is_custom_tag AND t.datatype IN ('monetary', 'shares', 'perShare', 'pure')
),
checked AS (
  SELECT *,
    CASE WHEN datatype = 'monetary' THEN regexp_matches(uom, '^[A-Z]{3}$')
         WHEN datatype = 'shares' THEN uom = 'shares'
         WHEN datatype = 'perShare' THEN regexp_matches(uom, '^[A-Z]{3}$')
         WHEN datatype = 'pure' THEN uom = 'pure' END AS ok
  FROM f
),
multi AS (
  SELECT adsh, tag, count(DISTINCT uom) AS n_uom, string_agg(DISTINCT uom, ',') AS uoms
  FROM f WHERE datatype = 'monetary' GROUP BY ALL HAVING count(DISTINCT uom) > 1
)
SELECT 'pass' AS status, count(*) AS n, NULL::BIGINT AS cik, NULL::VARCHAR AS adsh, NULL::DATE AS period_end,
       NULL::INTEGER AS qtrs, NULL::VARCHAR AS tag, NULL::DOUBLE AS observed, NULL::DOUBLE AS expected,
       NULL::DOUBLE AS diff, NULL::VARCHAR AS message
FROM checked WHERE ok
UNION ALL
SELECT 'fail', 1, cik, adsh, period_end, qtrs, tag, NULL, NULL, NULL,
       'unit ' || uom || ' inconsistent with datatype ' || datatype
FROM checked WHERE NOT ok
UNION ALL
SELECT 'fail', 1, NULL, adsh, NULL, NULL, tag, n_uom, 1, n_uom - 1,
       'monetary tag reported in several currencies within one filing: ' || uoms
FROM multi
