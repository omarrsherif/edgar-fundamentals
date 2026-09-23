# METRICS

Generated 2026-09-23T17:48:21+00:00 by `edgar-fundamentals metrics`. Every number below was measured on this machine
(Windows 11, 24 logical cores, 32 GB RAM, NVMe SSD, DuckDB 1.5).

## Data volume

| metric | value |
|---|---|
| quarters ingested | 8 (2024q3 to 2026q2) |
| rows ingested, all four files | 35,865,802 |
| of which num.txt (numeric facts) | 29,148,155 |
| of which sub.txt (submissions) | 53,158 |
| of which tag.txt | 700,766 |
| of which pre.txt | 5,963,723 |
| rows rejected by the CSV parser | 6 |
| filings covered (10-K / 10-Q families, modelled) | 45,957 of 53,158 submissions |
| distinct companies (modelled) | 6,570 of 7,917 |
| fact_financial_facts rows | 24,184,064 |
| fact_normalized rows | 1,716,574 (88,132 derived; 33 canonical metrics) |
| current-period span of modelled filings | 2018-12-31 to 2026-05-31 |

Forms in scope: 10-Q 33,801, 10-K 11,138, 10-Q/A 493, 10-K/A 490, 10-KT 29, 10-QT 3, 10-KT/A 2, 10-QT/A 1.

## Ingest performance

| quarter | ZIP bytes | download s | extract s | parse s | rows | rows/s (parse) | rejects |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2024q3 | 118,280,418 | 4.1 | 2.2 | 2.9 | 4,353,443 | 1,499,068 | 0 |
| 2024q4 | 122,932,548 | 2.1 | 2.4 | 3.1 | 4,533,438 | 1,467,344 | 0 |
| 2025q1 | 127,765,057 | 1.8 | 2.3 | 3.1 | 4,506,215 | 1,465,179 | 0 |
| 2025q2 | 78,973,768 | 1.4 | 1.9 | 3.0 | 4,276,187 | 1,426,686 | 0 |
| 2025q3 | 127,842,298 | 2.5 | 2.4 | 3.0 | 4,536,287 | 1,523,697 | 6 |
| 2025q4 | 65,830,170 | 1.2 | 2.0 | 2.9 | 4,643,534 | 1,602,752 | 0 |
| 2026q1 | 85,259,424 | 1.4 | 2.1 | 3.2 | 4,522,052 | 1,422,887 | 0 |
| 2026q2 | 60,419,016 | 1.1 | 2.1 | 3.3 | 4,494,646 | 1,349,004 | 0 |

| **total** | 787,302,699 | 15.5 | 17.5 | 24.5 | 35,865,802 | 1,466,843 | 6 |

- Ingest wall-clock (download + extract + parse, sequential): **57.5 s**
- Rows per second: **1,466,843** during DuckDB parsing, **624,035** end to end including download and extraction.
- Warehouse build (Parquet to DuckDB dims, facts, restatements, normalized layer): **84.3 s**
- Download timings reflect the first run; re-runs report every quarter as cached and download nothing.

## Storage and compression

| artifact | size |
|---|---:|
| raw ZIPs (SEC download cache) | 787.3 MB |
| extracted tab-delimited text | 5,218.4 MB (6.6x the ZIPs) |
| Parquet staging (ZSTD) | 489.2 MB |
| DuckDB warehouse file | 1,962.9 MB |

- DuckDB warehouse vs raw ZIPs: **2.49x**; vs extracted text: **0.38x**.
- Parquet staging vs raw ZIPs: **0.62x**; vs extracted text: **0.09x**.
- The warehouse is larger than the ZIPs because deflate on repetitive text is very effective and the warehouse stores the modelled facts plus restatements, normalized values and quality results; `raw_num` remains a view over the Parquet files rather than a second copy.

## Validation

- Rules implemented: **22**
- Units evaluated: 112,697,176; failures: 144,916; overall pass rate: **99.871%**
- Restatements detected: **94,141** facts reported with materially different values across filings (4,753 companies, 291,142 version rows kept, later filing authoritative); a further 16,811 differ only within rounding tolerance.
- Outliers flagged (robust z > 5 sigma vs the company's own history): **32,037**

| id | rule | category | severity | evaluated | failed | skipped | failure rate | coverage |
|---|---|---|---|---:|---:|---:|---:|---:|
| R01 | `balance_sheet_identity` | identity | error | 50,955 | 109 | 2,322 | 0.214% | 95.64% |
| R02 | `liabilities_plus_equity` | identity | error | 45,062 | 2,441 | 6,012 | 5.417% | 88.23% |
| R03 | `sign_conventions` | sign | warn | 1,219,812 | 60 | 0 | 0.005% | 100.00% |
| R04 | `revenue_nonnegative` | sign | warn | 90,285 | 134 | 0 | 0.148% | 100.00% |
| R05 | `current_assets_le_total_assets` | plausibility | error | 40,458 | 6 | 12,700 | 0.015% | 76.11% |
| R06 | `current_liabilities_le_total_liabilities` | plausibility | error | 40,361 | 26 | 11,714 | 0.064% | 77.51% |
| R07 | `period_continuity` | continuity | error | 93,517 | 2,798 | 129,843 | 2.992% | 41.87% |
| R08 | `quarters_sum_to_annual` | continuity | error | 2,224 | 155 | 79,390 | 6.969% | 2.73% |
| R09 | `restatement_detected` | restatement | info | 2,083,283 | 94,141 | 0 | 4.519% | 100.00% |
| R10 | `amendment_detected` | restatement | info | 44,971 | 554 | 0 | 1.232% | 100.00% |
| R11 | `duplicate_filing` | duplicate | warn | 44,971 | 8 | 0 | 0.018% | 100.00% |
| R12 | `duplicate_fact_rows` | duplicate | error | 29,148,155 | 406 | 0 | 0.001% | 100.00% |
| R13 | `outlier_robust_z` | outlier | error | 760,964 | 32,037 | 772,535 | 4.210% | 49.62% |
| R14 | `missing_mandatory_tags` | completeness | error | 45,854 | 1,693 | 0 | 3.692% | 100.00% |
| R15 | `unit_inconsistency` | unit | error | 9,336,484 | 276 | 0 | 0.003% | 100.00% |
| R16 | `gross_profit_consistency` | identity | error | 36,933 | 636 | 2,066 | 1.722% | 94.70% |
| R17 | `cash_flow_identity` | identity | error | 61,280 | 1,244 | 10,119 | 2.030% | 85.83% |
| R18 | `eps_consistency` | plausibility | error | 79,711 | 7,915 | 12,544 | 9.930% | 86.40% |
| R19 | `fiscal_period_validity` | referential | error | 45,957 | 9 | 0 | 0.020% | 100.00% |
| R20 | `tag_referential_integrity` | referential | error | 35,111,878 | 0 | 0 | 0.000% | 100.00% |
| R21 | `instant_duration_consistency` | referential | error | 24,049,856 | 0 | 134,208 | 0.000% | 99.45% |
| R22 | `value_magnitude_plausibility` | plausibility | error | 10,264,205 | 268 | 0 | 0.003% | 100.00% |


Top failure categories by share of failing rows:

| category | failed | evaluated | share of all failures |
|---|---:|---:|---:|
| restatement | 94,695 | 2,128,254 | 65.34% |
| outlier | 32,037 | 760,964 | 22.11% |
| plausibility | 8,215 | 10,424,735 | 5.67% |
| identity | 4,430 | 194,230 | 3.06% |
| continuity | 2,953 | 95,741 | 2.04% |
| completeness | 1,693 | 45,854 | 1.17% |
| duplicate | 414 | 29,193,126 | 0.29% |
| unit | 276 | 9,336,484 | 0.19% |
| sign | 194 | 1,310,097 | 0.13% |
| referential | 9 | 59,207,691 | 0.01% |


## Ratio layer

- 13 ratios x 91,083 company-periods (6,534 companies) = 1,184,079 rows, 706,139 with a value.
- Status mix: ok 521,014, null 477,940, derived 133,835, estimated 51,290.
- Most common null reasons: `missing` 406,844, `non_positive_equity` 35,286, `prior_period_not_found` 25,330, `zero_denominator` 8,170, `non_positive_prior_revenue` 1,909, `non_positive_denominator` 401.

## Query performance


Cold = fresh Python process + fresh read-only DuckDB connection per run; OS page cache not dropped. Warm = same connection, 50 timed runs after 5 warm-ups. Times are query execution inside the process (ms); a cold process additionally spends p50 614.7 ms opening the connection and 981.5 ms total wall-clock including interpreter start-up.


**Baseline, before the optimization pass** (frozen copy `bench/results/00_baseline.json`, measured with the same harness; kept verbatim). A cold process then spent p50 18.8 ms opening the connection and 1,041.0 ms total wall-clock.

| query | cold p50 | cold p95 | warm p50 | warm p95 | runs (cold/warm) |
|---|---:|---:|---:|---:|---:|
| `company_search` | 554.5 | 614.0 | 2.4 | 2.5 | 20/50 |
| `company_ratio_trend` | 8.8 | 10.2 | 3.7 | 4.4 | 20/50 |
| `multi_company_compare` | 7.0 | 8.3 | 4.5 | 5.2 | 20/50 |
| `sector_percentile` | 125.1 | 132.0 | 115.1 | 125.8 | 20/50 |
| `dq_summary` | 2.9 | 3.3 | 1.6 | 1.7 | 20/50 |

- Baseline dashboard load: cold 2.55 s, warm 0.88 s.

**Current, after the optimization pass** (what changed, what each change moved and what it cost: [bench/OPTIMIZATION.md](bench/OPTIMIZATION.md)). "saved" = baseline minus current p50.

| query | cold p50 | cold p95 | warm p50 | warm p95 | cold p50 saved | warm p50 saved | same-day control cold / warm p50 (no code change) | runs (cold/warm) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `company_search` | 3.4 | 3.7 | 4.2 | 6.2 | 551.1 ms (99%) | -1.9 ms (-80%) | 630.3 / 4.1 | 20/50 |
| `company_ratio_trend` | 8.8 | 11.2 | 6.2 | 8.4 | 0.0 ms (0%) | -2.6 ms (-71%) | 9.1 / 6.4 | 20/50 |
| `multi_company_compare` | 7.2 | 8.3 | 9.8 | 13.4 | -0.2 ms (-2%) | -5.3 ms (-117%) | 7.2 / 9.6 | 20/50 |
| `sector_percentile` | 21.8 | 23.2 | 33.6 | 39.4 | 103.3 ms (83%) | 81.5 ms (71%) | 131.2 / 235.6 | 20/50 |
| `dq_summary` | 2.9 | 3.2 | 2.9 | 4.3 | 0.0 ms (1%) | -1.3 ms (-80%) | 2.9 / 2.9 | 20/50 |


Negative "saved" values on the fast queries are within the same-day control column: the unchanged baseline code re-measured on the day of the optimization pass gave those warm numbers too (dashboard control: cold 3.62 s, warm 1.84 s). The offset is the machine on the day, not the code; details and the per-change table are in bench/OPTIMIZATION.md.



- Dashboard load (streamlit.testing.v1.AppTest full script execution (server side, no browser render); cold = first run in a fresh process, warm = second run in the same process): **cold 2.60 s**, warm 1.62 s.


## Tests


- pytest: **104 passed**, 0 failed, 0 errors, 0 skipped (104 collected, 29.4 s)
- Line coverage of `edgar_fundamentals` (excluding the Streamlit page script): **72.6%** (1,109 of 1,528 statements)
