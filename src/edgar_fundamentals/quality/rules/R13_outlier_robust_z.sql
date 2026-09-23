-- id: R13
-- name: outlier_robust_z
-- category: outlier
-- severity: error
-- unit: normalized monetary or share value (company, metric, period, duration)
-- description: Value more than 5 robust sigmas from the company's own history for the same metric and duration (z = (x - median) / (1.4826 * MAD); mean absolute deviation fallback when MAD = 0). Skipped with fewer than 9 observations or a constant history.
WITH v AS (
  SELECT cik, metric, qtrs, period_end, value, source_adsh
  FROM fact_normalized WHERE datatype IN ('monetary', 'shares')
),
s AS (
  SELECT cik, metric, qtrs, count(*) AS n, median(value) AS med FROM v GROUP BY ALL
),
dev AS (
  SELECT v.cik, v.metric, v.qtrs, median(abs(v.value - s.med)) AS mad, avg(abs(v.value - s.med)) AS mean_ad
  FROM v JOIN s USING (cik, metric, qtrs) GROUP BY ALL
),
z AS (
  SELECT v.*, s.n, s.med,
    CASE WHEN dev.mad > 0 THEN (v.value - s.med) / (1.4826 * dev.mad)
         WHEN dev.mean_ad > 0 THEN (v.value - s.med) / (1.2533 * dev.mean_ad)
         ELSE NULL END AS z
  FROM v JOIN s USING (cik, metric, qtrs) JOIN dev USING (cik, metric, qtrs)
)
SELECT
  CASE WHEN n < ${outlier_min_history} + 1 THEN 'skip'
       WHEN z IS NULL THEN 'skip'
       WHEN abs(z) > ${outlier_sigma} THEN 'fail'
       ELSE 'pass' END AS status,
  cik, source_adsh AS adsh, period_end, qtrs, metric AS tag,
  value AS observed, med AS expected, value - med AS diff,
  'robust z = ' || round(z, 1) || ' against ' || n || ' company observations' AS message
FROM z
