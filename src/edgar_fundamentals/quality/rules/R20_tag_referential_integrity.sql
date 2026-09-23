-- id: R20
-- name: tag_referential_integrity
-- category: referential
-- severity: error
-- unit: raw num.txt row and raw pre.txt row (all forms, all quarters)
-- description: Every (tag, version) used in num.txt and pre.txt must exist in tag.txt, and every num.txt accession must exist in sub.txt.
WITH tags AS (SELECT DISTINCT tag, version FROM raw_tag),
subs AS (SELECT DISTINCT adsh FROM raw_sub),
num_tag_missing AS (
  SELECT n.adsh, n.tag, n.version, TRY_STRPTIME(n.ddate, '%Y%m%d')::DATE AS period_end, n.qtrs
  FROM raw_num n ANTI JOIN tags t ON t.tag = n.tag AND t.version = n.version
),
num_sub_missing AS (
  SELECT n.adsh, n.tag, TRY_STRPTIME(n.ddate, '%Y%m%d')::DATE AS period_end, n.qtrs
  FROM raw_num n ANTI JOIN subs s ON s.adsh = n.adsh
),
pre_tag_missing AS (
  SELECT p.adsh, p.tag, p.version
  FROM raw_pre p ANTI JOIN tags t ON t.tag = p.tag AND t.version = p.version
),
totals AS (SELECT (SELECT count(*) FROM raw_num) + (SELECT count(*) FROM raw_pre) AS n)
SELECT 'pass' AS status,
       (SELECT n FROM totals) - (SELECT count(*) FROM num_tag_missing)
         - (SELECT count(*) FROM num_sub_missing) - (SELECT count(*) FROM pre_tag_missing) AS n,
       NULL::BIGINT AS cik, NULL::VARCHAR AS adsh, NULL::DATE AS period_end, NULL::INTEGER AS qtrs,
       NULL::VARCHAR AS tag, NULL::DOUBLE AS observed, NULL::DOUBLE AS expected, NULL::DOUBLE AS diff,
       NULL::VARCHAR AS message
UNION ALL
SELECT 'fail', 1, NULL, adsh, period_end, qtrs, tag, NULL, NULL, NULL, 'num tag/version ' || version || ' not in tag.txt' FROM num_tag_missing
UNION ALL
SELECT 'fail', 1, NULL, adsh, period_end, qtrs, tag, NULL, NULL, NULL, 'num accession not in sub.txt' FROM num_sub_missing
UNION ALL
SELECT 'fail', 1, NULL, adsh, NULL, NULL, tag, NULL, NULL, NULL, 'pre tag/version ' || version || ' not in tag.txt' FROM pre_tag_missing
