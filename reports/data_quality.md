# Data quality report

Generated 2026-09-23T15:49:02+00:00. 22 rules; 112,697,176 units evaluated; 144,916 failures; overall pass rate **99.871%**.

Failure rate = failed / (passed + failed). Coverage = evaluated / (evaluated + skipped), where a unit is skipped when the rule's inputs are not reported.

## Per rule

| id | rule | category | severity | unit | evaluated | passed | failed | skipped | failure rate | coverage |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|
| R01 | `balance_sheet_identity` | identity | error | company balance-sheet date with reported total assets or total liabilities-and-equity | 50,955 | 50,846 | 109 | 2,322 | 0.214% | 95.642% |
| R02 | `liabilities_plus_equity` | identity | error | company balance-sheet date with reported liabilities-and-equity | 45,062 | 42,621 | 2,441 | 6,012 | 5.417% | 88.229% |
| R03 | `sign_conventions` | sign | warn | consolidated fact for a tag whose natural balance is non-negative (list in config/quality_rules.yaml) | 1,219,812 | 1,219,752 | 60 | 0 | 0.005% | 100.000% |
| R04 | `revenue_nonnegative` | sign | warn | normalized revenue value (company, period, duration) | 90,285 | 90,151 | 134 | 0 | 0.148% | 100.000% |
| R05 | `current_assets_le_total_assets` | plausibility | error | company balance-sheet date with reported total assets | 40,458 | 40,452 | 6 | 12,700 | 0.015% | 76.109% |
| R06 | `current_liabilities_le_total_liabilities` | plausibility | error | company balance-sheet date with total liabilities (reported or derived) | 40,361 | 40,335 | 26 | 11,714 | 0.064% | 77.506% |
| R07 | `period_continuity` | continuity | error | year-to-date flow value (company, metric, period end) for revenue, cost of revenue, operating income, net income, operating cash flow | 93,517 | 90,719 | 2,798 | 129,843 | 2.992% | 41.868% |
| R08 | `quarters_sum_to_annual` | continuity | error | (company, metric, fiscal year) with a reported annual value | 2,224 | 2,069 | 155 | 79,390 | 6.969% | 2.725% |
| R09 | `restatement_detected` | restatement | info | consolidated fact (company, tag, period, duration, unit) reported in two or more filings | 2,083,283 | 1,989,142 | 94,141 | 0 | 4.519% | 100.000% |
| R10 | `amendment_detected` | restatement | info | original (non-amended) in-scope filing | 44,971 | 44,417 | 554 | 0 | 1.232% | 100.000% |
| R11 | `duplicate_filing` | duplicate | warn | original (non-amended) in-scope filing | 44,971 | 44,963 | 8 | 0 | 0.018% | 100.000% |
| R12 | `duplicate_fact_rows` | duplicate | error | raw num.txt row (all forms, all quarters) | 29,148,155 | 29,147,749 | 406 | 0 | 0.001% | 100.000% |
| R13 | `outlier_robust_z` | outlier | error | normalized monetary or share value (company, metric, period, duration) | 760,964 | 728,927 | 32,037 | 772,535 | 4.210% | 49.623% |
| R14 | `missing_mandatory_tags` | completeness | error | 10-K / 10-Q filing that carries a balance sheet | 45,854 | 44,161 | 1,693 | 0 | 3.692% | 100.000% |
| R15 | `unit_inconsistency` | unit | error | consolidated fact with a typed tag (monetary / shares / perShare / pure) | 9,336,484 | 9,336,208 | 276 | 0 | 0.003% | 100.000% |
| R16 | `gross_profit_consistency` | identity | error | company flow period with a reported GrossProfit | 36,933 | 36,297 | 636 | 2,066 | 1.722% | 94.702% |
| R17 | `cash_flow_identity` | identity | error | company flow period with reported operating cash flow | 61,280 | 60,036 | 1,244 | 10,119 | 2.030% | 85.828% |
| R18 | `eps_consistency` | plausibility | error | company flow period with reported basic EPS | 79,711 | 71,796 | 7,915 | 12,544 | 9.930% | 86.403% |
| R19 | `fiscal_period_validity` | referential | error | in-scope filing | 45,957 | 45,948 | 9 | 0 | 0.020% | 100.000% |
| R20 | `tag_referential_integrity` | referential | error | raw num.txt row and raw pre.txt row (all forms, all quarters) | 35,111,878 | 35,111,878 | 0 | 0 | 0.000% | 100.000% |
| R21 | `instant_duration_consistency` | referential | error | modelled fact whose tag declares an instant/duration period type | 24,049,856 | 24,049,856 | 0 | 134,208 | 0.000% | 99.445% |
| R22 | `value_magnitude_plausibility` | plausibility | error | consolidated monetary / share / per-share fact | 10,264,205 | 10,263,937 | 268 | 0 | 0.003% | 100.000% |

## Top failure categories (share of failing rows)

| category | failed | evaluated | share of all failures |
|---|---:|---:|---:|
| restatement | 94,695 | 2,128,254 | 65.345% |
| outlier | 32,037 | 760,964 | 22.107% |
| plausibility | 8,215 | 10,424,735 | 5.669% |
| identity | 4,430 | 194,230 | 3.057% |
| continuity | 2,953 | 95,741 | 2.038% |
| completeness | 1,693 | 45,854 | 1.168% |
| duplicate | 414 | 29,193,126 | 0.286% |
| unit | 276 | 9,336,484 | 0.190% |
| sign | 194 | 1,310,097 | 0.134% |
| referential | 9 | 59,207,691 | 0.006% |

## Restatements

- 94,141 (company, tag, period, duration, unit) facts reported with materially different values in different filings, across 4,753 companies; 291,142 version rows kept, later filing marked authoritative.
- 16,811 further facts differ only within the rounding tolerance.

## Outliers

- 32,037 normalized values flagged beyond the robust z threshold.

## Companies with most failures (error/warn)

| cik | company | failures | rules hit |
|---|---|---:|---:|
| 1755953 | AMERICAN BITCOIN CORP. | 60 | 6 |
| 1051512 | TELEPHONE & DATA SYSTEMS INC /DE/ | 57 | 4 |
| 1920406 | STRIVE, INC. | 55 | 5 |
| 1666700 | DUPONT DE NEMOURS, INC. | 55 | 3 |
| 819926 | SHARING ECONOMY INTERNATIONAL INC. | 53 | 1 |
| 1569187 | AH REALTY TRUST, INC. | 51 | 5 |
| 1918080 | DEEP ISOLATION NUCLEAR, INC. | 51 | 4 |
| 1819810 | REDWIRE CORP | 49 | 2 |
| 1911545 | GLOBAL INTERACTIVE TECHNOLOGIES, INC. | 49 | 3 |
| 1368622 | AEROVIRONMENT INC | 49 | 1 |

## Rule descriptions

- **R01 `balance_sheet_identity`** - Total assets must equal LiabilitiesAndStockholdersEquity within 0.1% (floor USD 1,000). Skipped when only one side is reported.
- **R02 `liabilities_plus_equity`** - Reported total liabilities + total equity (incl. NCI) + temporary equity must equal LiabilitiesAndStockholdersEquity within 0.5%. Skipped when Liabilities is not reported (derived values would be tautological).
- **R03 `sign_conventions`** - Assets, liabilities, inventory, receivables, cash, cost of revenue, capex and share counts must not be negative.
- **R04 `revenue_nonnegative`** - Revenue should not be negative. Warn-level because RevenuesNetOfInterestExpense can legitimately be negative for financial firms.
- **R05 `current_assets_le_total_assets`** - Current assets cannot exceed total assets (0.1% tolerance). Skipped for unclassified balance sheets that report no current assets.
- **R06 `current_liabilities_le_total_liabilities`** - Current liabilities cannot exceed total liabilities (0.1% tolerance). Skipped when no current liabilities are reported.
- **R07 `period_continuity`** - A year-to-date value must equal the previous year-to-date value plus the quarter: YTD(n) = YTD(n-1) + Q(n), within 0.5%. Skipped when either component is not reported (e.g. Q4 is almost never filed as a standalone quarter).
- **R08 `quarters_sum_to_annual`** - Where all four standalone quarters are reported, they must sum to the annual value within 0.5%. Coverage is low because Q4 is rarely filed as a standalone quarter.
- **R09 `restatement_detected`** - The same fact reported with materially different values (>0.1%) in different filings. Both values are kept in the restatements table; the later filing is authoritative.
- **R10 `amendment_detected`** - An original 10-K/10-Q that was later superseded by a 10-K/A or 10-Q/A for the same company and period. Computed from the data rather than the stale prevrpt flag.
- **R11 `duplicate_filing`** - The same company filed the same form for the same period more than once without marking it as an amendment.
- **R12 `duplicate_fact_rows`** - Exact duplicates of the num.txt primary key (adsh, tag, version, ddate, qtrs, uom, segments, coreg) inside one dataset quarter. Every row of a duplicated key counts as a failure.
- **R13 `outlier_robust_z`** - Value more than 5 robust sigmas from the company's own history for the same metric and duration (z = (x - median) / (1.4826 * MAD); mean absolute deviation fallback when MAD = 0). Skipped with fewer than 9 observations or a constant history.
- **R14 `missing_mandatory_tags`** - Every primary filing must report the mandatory canonical metrics for its form (config/mandatory_tags.yaml) after alias resolution; revenue is not required for financial-sector SICs, and only required when the filing reports cost of revenue or gross profit (pre-revenue and investment companies have no revenue line).
- **R15 `unit_inconsistency`** - The unit of measure must match the tag's datatype (monetary -> ISO currency, shares -> shares, perShare -> ISO currency (FSDS stores per-share units as the bare currency), pure -> pure); additionally a monetary tag must not be reported in two currencies inside one filing.
- **R16 `gross_profit_consistency`** - Revenue - cost of revenue must equal reported gross profit within 0.5%. Skipped when revenue or cost of revenue is not reported.
- **R17 `cash_flow_identity`** - Operating + investing + financing cash flow (+ FX effect) must equal the reported change in cash within 0.5%, pairing the including-FX or excluding-FX variant of the change-in-cash tag. Skipped when a component or the change-in-cash total is not reported.
- **R18 `eps_consistency`** - Net income / weighted-average basic shares must agree with reported basic EPS within 5% (floor 0.01). Catches share counts or EPS reported at the wrong scale. Skipped when net income or basic shares are missing or zero.
- **R19 `fiscal_period_validity`** - Submission metadata must be coherent: period and filed present, fp in the allowed set, fy within one year of the period, period not after the filing date, and 10-K forms tagged fp = FY.
- **R20 `tag_referential_integrity`** - Every (tag, version) used in num.txt and pre.txt must exist in tag.txt, and every num.txt accession must exist in sub.txt.
- **R21 `instant_duration_consistency`** - Instant tags (iord = I, balance-sheet items) must be reported with qtrs = 0. Duration tags with qtrs = 0 are skipped: FSDS rounds durations shorter than ~45 days (e.g. a share issuance on a single date) to zero quarters, so they cannot be judged.
- **R22 `value_magnitude_plausibility`** - Values beyond physically plausible magnitudes (USD > 1e14, shares > 1e13, per-share > 1e5) indicate scaling errors in the filing.
