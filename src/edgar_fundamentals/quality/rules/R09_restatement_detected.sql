-- id: R09
-- name: restatement_detected
-- category: restatement
-- severity: info
-- unit: consolidated fact (company, tag, period, duration, unit) reported in two or more filings
-- description: The same fact reported with materially different values (>0.1%) in different filings. Both values are kept in the restatements table; the later filing is authoritative.
WITH groups AS (
  SELECT cik, tag, period_end, qtrs, uom
  FROM fact_financial_facts
  WHERE is_consolidated AND NOT is_custom_tag AND taxonomy <> 'dei'
  GROUP BY ALL HAVING count(DISTINCT adsh) > 1
),
r AS (
  SELECT cik, tag, period_end, qtrs, uom,
         any_value(classification) AS classification, max(n_versions) AS n_versions,
         max(group_max_rel_diff) AS max_rel, any_value(authoritative_adsh) AS adsh,
         any_value(authoritative_value) AS auth_value, arg_min(value, filed) AS first_value
  FROM restatements GROUP BY ALL
)
SELECT 'pass' AS status, count(*) AS n, NULL::BIGINT AS cik, NULL::VARCHAR AS adsh, NULL::DATE AS period_end,
       NULL::INTEGER AS qtrs, NULL::VARCHAR AS tag, NULL::DOUBLE AS observed, NULL::DOUBLE AS expected,
       NULL::DOUBLE AS diff, NULL::VARCHAR AS message
FROM groups g LEFT JOIN r USING (cik, tag, period_end, qtrs, uom)
WHERE r.classification IS NULL OR r.classification = 'rounding_diff'
UNION ALL
SELECT 'fail', 1, cik, adsh, period_end, qtrs, tag, auth_value, first_value, auth_value - first_value,
       'reported in ' || n_versions || ' filings, values differ by up to ' || round(max_rel * 100, 2) || '%'
FROM r WHERE classification = 'restatement'
