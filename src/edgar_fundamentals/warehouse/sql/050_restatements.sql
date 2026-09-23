-- restatements: the same consolidated fact (company, tag, period, duration, unit) reported with
-- different values in different filings. Every version is kept; the latest filed one (amendment wins
-- ties) is authoritative. Differences within the rounding tolerance are classified rounding_diff.
CREATE OR REPLACE TABLE restatements AS
WITH c AS (
  SELECT cik, tag, period_end, qtrs, uom, adsh, form, filed, value, is_current_period, version
  FROM fact_financial_facts
  WHERE is_consolidated AND NOT is_custom_tag AND taxonomy <> 'dei'
  QUALIFY row_number() OVER (PARTITION BY cik, tag, period_end, qtrs, uom, adsh ORDER BY version DESC) = 1
),
g AS (
  SELECT cik, tag, period_end, qtrs, uom
  FROM c GROUP BY ALL
  HAVING count(*) > 1 AND count(DISTINCT value) > 1
),
v AS (
  SELECT c.*,
    row_number() OVER w = 1 AS is_authoritative,
    first_value(value) OVER w AS authoritative_value,
    first_value(adsh) OVER w AS authoritative_adsh,
    first_value(form) OVER w AS authoritative_form,
    first_value(filed) OVER w AS authoritative_filed,
    count(*) OVER (PARTITION BY cik, tag, period_end, qtrs, uom) AS n_versions
  FROM c JOIN g USING (cik, tag, period_end, qtrs, uom)
  WINDOW w AS (PARTITION BY cik, tag, period_end, qtrs, uom
               ORDER BY filed DESC, (form LIKE '%/A') DESC, adsh DESC)
),
d AS (
  SELECT *,
    value - authoritative_value AS delta,
    abs(value - authoritative_value) / nullif(greatest(abs(value), abs(authoritative_value)), 0) AS rel_diff
  FROM v
),
m AS (
  SELECT *, max(rel_diff) OVER (PARTITION BY cik, tag, period_end, qtrs, uom) AS group_max_rel_diff FROM d
)
SELECT *,
  CASE WHEN group_max_rel_diff > ${restatement_rel} THEN 'restatement' ELSE 'rounding_diff' END AS classification
FROM m;
