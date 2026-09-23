-- id: R12
-- name: duplicate_fact_rows
-- category: duplicate
-- severity: error
-- unit: raw num.txt row (all forms, all quarters)
-- description: Exact duplicates of the num.txt primary key (adsh, tag, version, ddate, qtrs, uom, segments, coreg) inside one dataset quarter. Every row of a duplicated key counts as a failure.
WITH h AS (
  SELECT dataset_quarter, hash(adsh, tag, version, ddate, qtrs, uom, segments, coreg) AS k, count(*) AS n
  FROM raw_num GROUP BY ALL HAVING count(*) > 1
),
d AS (
  SELECT n.dataset_quarter, n.adsh, n.tag, n.ddate, n.qtrs, h.n
  FROM raw_num n JOIN h ON h.dataset_quarter = n.dataset_quarter
                       AND h.k = hash(n.adsh, n.tag, n.version, n.ddate, n.qtrs, n.uom, n.segments, n.coreg)
  QUALIFY row_number() OVER (PARTITION BY n.dataset_quarter, h.k) = 1
)
SELECT 'pass' AS status, (SELECT count(*) FROM raw_num) - coalesce((SELECT sum(n) FROM h), 0) AS n,
       NULL::BIGINT AS cik, NULL::VARCHAR AS adsh, NULL::DATE AS period_end, NULL::INTEGER AS qtrs,
       NULL::VARCHAR AS tag, NULL::DOUBLE AS observed, NULL::DOUBLE AS expected, NULL::DOUBLE AS diff,
       NULL::VARCHAR AS message
UNION ALL
SELECT 'fail', n, NULL, adsh, TRY_STRPTIME(ddate, '%Y%m%d')::DATE, qtrs, tag, n, 1, n - 1,
       'key duplicated ' || n || 'x in ' || dataset_quarter || ' num.txt'
FROM d
