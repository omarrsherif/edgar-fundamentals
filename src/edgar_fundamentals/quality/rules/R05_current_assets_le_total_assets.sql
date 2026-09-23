-- id: R05
-- name: current_assets_le_total_assets
-- category: plausibility
-- severity: error
-- unit: company balance-sheet date with reported total assets
-- description: Current assets cannot exceed total assets (0.1% tolerance). Skipped for unclassified balance sheets that report no current assets.
SELECT
  CASE WHEN current_assets IS NULL THEN 'skip'
       WHEN current_assets <= total_assets + greatest(${face_total_rel} * abs(total_assets), ${abs_floor}) THEN 'pass'
       ELSE 'fail' END AS status,
  cik, adsh, period_end, qtrs, 'AssetsCurrent' AS tag,
  current_assets AS observed, total_assets AS expected, current_assets - total_assets AS diff,
  'AssetsCurrent > Assets' AS message
FROM dq_wide
WHERE qtrs = 0 AND total_assets IS NOT NULL
