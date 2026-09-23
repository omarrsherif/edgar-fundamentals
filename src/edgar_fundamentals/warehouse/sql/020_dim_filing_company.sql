-- dim_filing: one row per accession number (a filing seen in two dataset quarters keeps the latest copy).
CREATE OR REPLACE TABLE dim_filing AS
WITH s AS (
  SELECT *,
    TRY_STRPTIME(period, '%Y%m%d')::DATE AS period_date,
    TRY_STRPTIME(filed, '%Y%m%d')::DATE AS filed_date
  FROM raw_sub
  QUALIFY row_number() OVER (PARTITION BY adsh ORDER BY dataset_quarter DESC) = 1
)
SELECT
  adsh, cik, name, sic, form,
  period_date AS period,
  fy AS fy_reported, fp AS fp_reported,
  filed_date AS filed, accepted,
  prevrpt = 1 AS prevrpt, detail = 1 AS detail, nciks, aciks, fye, afs, wksi,
  stprinc AS state_of_inc, countryinc AS country_of_inc, stprba AS state_ba, countryba AS country_ba,
  dataset_quarter,
  form LIKE '%/A' AS is_amendment,
  form IN (${in_scope_forms}) AS in_scope,
  CASE WHEN form LIKE '10-K%' THEN 'annual' WHEN form LIKE '10-Q%' THEN 'quarterly' ELSE 'other' END AS report_type,
  'https://www.sec.gov/Archives/edgar/data/' || cik || '/' || replace(adsh, '-', '') || '/' || adsh || '-index.htm' AS edgar_url
FROM s;

-- dim_company: one row per CIK. Name from the latest filing; SIC from the latest filing that has one;
-- fiscal year-end month from `fye` (fallback: month of the latest 10-K period, else December).
CREATE OR REPLACE TABLE dim_company AS
WITH latest AS (
  SELECT cik, name, fye, state_of_inc, country_of_inc, state_ba, country_ba, afs
  FROM dim_filing
  QUALIFY row_number() OVER (PARTITION BY cik ORDER BY filed DESC, adsh DESC) = 1
),
sic_latest AS (
  SELECT cik, sic FROM dim_filing WHERE sic IS NOT NULL AND sic > 0
  QUALIFY row_number() OVER (PARTITION BY cik ORDER BY filed DESC, adsh DESC) = 1
),
fye_latest AS (
  SELECT cik, fye FROM dim_filing
  WHERE fye IS NOT NULL AND length(fye) = 4 AND TRY_CAST(substr(fye, 1, 2) AS INTEGER) BETWEEN 1 AND 12
  QUALIFY row_number() OVER (PARTITION BY cik ORDER BY filed DESC, adsh DESC) = 1
),
fye_10k AS (
  SELECT cik, month(period) AS m FROM dim_filing WHERE report_type = 'annual' AND period IS NOT NULL
  QUALIFY row_number() OVER (PARTITION BY cik ORDER BY filed DESC, adsh DESC) = 1
),
agg AS (
  SELECT cik,
    min(filed) AS first_filed, max(filed) AS last_filed, count(*) AS n_filings,
    count(*) FILTER (WHERE in_scope) AS n_in_scope_filings,
    count(*) FILTER (WHERE report_type = 'annual') AS n_annual,
    count(*) FILTER (WHERE report_type = 'quarterly') AS n_quarterly
  FROM dim_filing GROUP BY cik
)
SELECT
  l.cik, l.name, s.sic,
  coalesce(m.division, 'Unknown') AS sector,
  coalesce(m.industry, 'Unknown') AS industry,
  m.major_group,
  EXISTS (SELECT 1 FROM financial_sic_ranges r WHERE s.sic BETWEEN r.sic_from AND r.sic_to) AS is_financial,
  l.state_of_inc, l.country_of_inc, l.state_ba, l.country_ba, l.afs AS filer_status,
  coalesce(f.fye, l.fye) AS fye,
  coalesce(TRY_CAST(substr(f.fye, 1, 2) AS INTEGER), k.m, 12) AS fiscal_year_end_month,
  (f.fye IS NULL AND k.m IS NULL) AS fiscal_year_end_assumed,
  a.first_filed, a.last_filed, a.n_filings, a.n_in_scope_filings, a.n_annual, a.n_quarterly
FROM latest l
LEFT JOIN sic_latest s USING (cik)
LEFT JOIN fye_latest f USING (cik)
LEFT JOIN fye_10k k USING (cik)
LEFT JOIN agg a USING (cik)
LEFT JOIN sic_sector_map m ON s.sic BETWEEN m.sic_from AND m.sic_to;
