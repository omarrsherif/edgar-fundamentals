-- id: R03
-- name: sign_conventions
-- category: sign
-- severity: warn
-- unit: consolidated fact for a tag whose natural balance is non-negative (list in config/quality_rules.yaml)
-- description: Assets, liabilities, inventory, receivables, cash, cost of revenue, capex and share counts must not be negative.
WITH tags AS (
  SELECT tag, taxonomy::VARCHAR AS taxonomy FROM (VALUES ${non_negative_tags}) v(tag, taxonomy)
),
f AS (
  SELECT f.cik, f.adsh, f.period_end, f.qtrs, f.tag, f.value
  FROM fact_financial_facts f
  JOIN tags t ON t.tag = f.tag AND (t.taxonomy IS NULL OR t.taxonomy = f.taxonomy)
  WHERE f.is_consolidated AND NOT f.is_custom_tag
)
SELECT 'pass' AS status, count(*) AS n, NULL::BIGINT AS cik, NULL::VARCHAR AS adsh, NULL::DATE AS period_end,
       NULL::INTEGER AS qtrs, NULL::VARCHAR AS tag, NULL::DOUBLE AS observed, NULL::DOUBLE AS expected,
       NULL::DOUBLE AS diff, NULL::VARCHAR AS message
FROM f WHERE value >= 0
UNION ALL
SELECT 'fail', 1, cik, adsh, period_end, qtrs, tag, value, 0, value,
       'negative value for a tag whose natural balance is non-negative'
FROM f WHERE value < 0
