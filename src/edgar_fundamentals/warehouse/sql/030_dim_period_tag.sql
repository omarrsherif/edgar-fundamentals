-- dim_period: every (period end, duration in quarters) pair that occurs in the data.
-- FSDS rounds period ends to month-end, so period_start is the day after the previous month-end.
CREATE OR REPLACE TABLE dim_period AS
WITH p AS (
  SELECT DISTINCT TRY_STRPTIME(ddate, '%Y%m%d')::DATE AS period_end, qtrs
  FROM raw_num WHERE ddate IS NOT NULL AND qtrs IS NOT NULL
)
SELECT
  strftime(period_end, '%Y%m%d') || '-' || qtrs AS period_key,
  period_end,
  qtrs AS duration_quarters,
  qtrs = 0 AS is_instant,
  CASE WHEN qtrs = 0 THEN NULL
       ELSE (last_day((period_end - to_months(3 * qtrs))::DATE) + INTERVAL 1 DAY)::DATE END AS period_start,
  CASE qtrs WHEN 0 THEN 'instant' WHEN 1 THEN 'quarter' WHEN 2 THEN 'half_year_ytd'
            WHEN 3 THEN 'nine_month_ytd' WHEN 4 THEN 'annual' ELSE 'other' END AS period_type,
  year(period_end) AS calendar_year,
  quarter(period_end) AS calendar_quarter
FROM p WHERE period_end IS NOT NULL;

-- dim_tag: taxonomy metadata, one row per (tag, version).
CREATE OR REPLACE TABLE dim_tag AS
SELECT tag, version, split_part(version, '/', 1) AS taxonomy,
  custom = 1 AS is_custom, abstract = 1 AS is_abstract, datatype, iord, crdr, tlabel, doc
FROM raw_tag
QUALIFY row_number() OVER (PARTITION BY tag, version ORDER BY dataset_quarter DESC) = 1;
