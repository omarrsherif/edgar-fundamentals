-- fact_financial_facts: every numeric fact from in-scope filings (10-K / 10-Q families), at the
-- num.txt grain (adsh, tag, version, period, qtrs, uom, segments, coreg). Dimensional facts are kept
-- and flagged; downstream layers filter on is_consolidated.
-- fiscal_year / fiscal_quarter are derived from the company's fiscal year-end month, not from the
-- filer-entered fy/fp on the submission (which describe the filing, not each comparative fact).
CREATE OR REPLACE TABLE fact_financial_facts AS
WITH n AS (
  SELECT *, TRY_STRPTIME(ddate, '%Y%m%d')::DATE AS period_end
  FROM raw_num
  WHERE value IS NOT NULL
  QUALIFY row_number() OVER (PARTITION BY adsh, tag, version, ddate, qtrs, uom, segments, coreg
                             ORDER BY dataset_quarter DESC) = 1
)
SELECT
  n.adsh, f.cik, n.tag, n.version,
  split_part(n.version, '/', 1) AS taxonomy,
  n.version = n.adsh AS is_custom_tag,
  strftime(n.period_end, '%Y%m%d') || '-' || n.qtrs AS period_key,
  n.period_end, n.qtrs, n.uom, n.value, n.segments, n.coreg, n.footnote,
  f.form, f.filed, f.report_type, f.period AS filing_period,
  (n.segments IS NULL AND n.coreg IS NULL) AS is_consolidated,
  (n.period_end = f.period) AS is_current_period,
  CASE WHEN month(n.period_end) <= c.fiscal_year_end_month THEN year(n.period_end)
       ELSE year(n.period_end) + 1 END AS fiscal_year,
  CASE WHEN ((c.fiscal_year_end_month - month(n.period_end) + 12) % 12) % 3 = 0
       THEN 4 - ((c.fiscal_year_end_month - month(n.period_end) + 12) % 12) // 3
       ELSE NULL END AS fiscal_quarter,
  n.dataset_quarter
FROM n
JOIN dim_filing f USING (adsh)
JOIN dim_company c USING (cik)
WHERE f.in_scope AND n.period_end IS NOT NULL;
