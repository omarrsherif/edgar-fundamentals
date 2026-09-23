# Optimization pass: dashboard query latency

Date: 2026-09-23. Machine: one desktop, Windows 11 Pro, Intel i9-12900KF (24 threads, 3.2 GHz base, "High performance" power plan), 32 GB RAM, NVMe; Python 3.12.13, DuckDB 1.5.5, pandas 3.0.6. Warehouse: `data/warehouse.duckdb`, 1.83 GiB, 8 quarters of SEC Financial Statement Data Sets (2024q3 to 2026q2).

Method, stated once: every number below comes from the **unchanged** benchmark harness in `src/edgar_fundamentals/bench/run.py`: 20 cold runs (each a fresh Python process and a fresh read-only DuckDB connection; the OS page cache is *not* dropped), 50 warm runs on one connection after 5 warm-ups, p50/p95 by linear interpolation (`bench.run.pct`), timing = `con.execute(sql, params).fetchall()` measured with `perf_counter` inside the process. Dashboard load = `streamlit.testing.v1.AppTest` full script run in a fresh process (cold) and a second run in the same process (warm), server side, no browser. The harness was not modified during the pass; the only CLI addition (`bench --out`) copies the result file after the measurement. Each saved result is one full harness run: `bench/results/*.json`. The tables are generated from those files by `uv run python -m edgar_fundamentals.bench.optimization_report`; nothing in a table is typed by hand.

## 1. Baseline (as given, frozen: `bench/results/00_baseline.json`)

| query | cold p50 | cold p95 | warm p50 | warm p95 |
|---|---:|---:|---:|---:|
| company_search | 554.5 ms | 614.0 ms | 2.4 ms | 2.5 ms |
| sector_percentile | 125.1 ms | 132.0 ms | 115.1 ms | 125.8 ms |
| company_ratio_trend | 8.8 ms | 10.2 ms | 3.7 ms | 4.4 ms |
| multi_company_compare | 7.0 ms | 8.3 ms | 4.5 ms | 5.2 ms |
| dq_summary | 2.9 ms | 3.3 ms | 1.6 ms | 1.7 ms |
| dashboard load | cold 2.55 s | | warm 0.88 s | |

A cold process in the baseline also spent p50 18.8 ms opening the connection and 1,041.0 ms total wall-clock (interpreter start-up, imports, connect, five queries).

### 1a. Noise floor: the unchanged harness re-run twice before any change

| run | company_search cold p50 / warm p50 | company_ratio_trend cold p50 / warm p50 | multi_company_compare cold p50 / warm p50 | sector_percentile cold p50 / warm p50 | dq_summary cold p50 / warm p50 | dashboard cold / warm (s) |
|---|---:|---:|---:|---:|---:|---:|
| baseline (frozen) | 554.5 / 2.4 | 8.8 / 3.7 | 7.0 / 4.5 | 125.1 / 115.1 | 2.9 / 1.6 | 2.55 / 0.88 |
| control re-run 1 (no code change) | 699.7 / 4.5 | 9.3 / 6.2 | 7.4 / 10.1 | 130.9 / 231.5 | 3.0 / 3.4 | 3.51 / 1.96 |
| control re-run 2 (no code change) | 630.3 / 4.1 | 9.1 / 6.4 | 7.2 / 9.6 | 131.2 / 235.6 | 2.9 / 2.9 | 3.62 / 1.84 |

Reading this table is a precondition for reading anything below. Cold p50s reproduced within 2 to 26 % (company_search 554.5 to 630 and 700; sector 125.1 to 131). The **warm** numbers did not: with no code change, warm sector_percentile measured 231.5 and 235.6 ms against the frozen 115.1 ms, and every warm p50 of the fast queries roughly doubled (2.4 to 4.1 ms, 4.5 to 9.6 ms). Dashboard load re-measured at 3.5 to 3.6 s cold and 1.8 to 2.0 s warm against 2.55 s / 0.88 s. I could not reproduce the baseline warm numbers on the day of the pass, and I did not tune anything to get closer to them. The mechanism for the sector query is identified in section 2 (Python garbage collection over the materialised result); for the dashboard it is not identified beyond "the Python side of the machine was slower on the day". Consequently: **deltas per change are computed against the measurement immediately before that change** (same day, same machine state), and the **final table shows the frozen baseline, the same-day control and the final numbers side by side** so the reader can see which differences are the code and which are the day.

## 2. Diagnosis before changing anything

Plans: `bench/plans/before/<query>.cold.txt` and `.warm.txt` (EXPLAIN ANALYZE as the first statement of a fresh process, and after five executions on one connection), `bench/plans/before/company_search_bisection.txt` (reproducible with `uv run edgar-fundamentals plans`).

### company_search: 554 ms cold vs 2.4 ms warm is neither the page cache nor the plan

The plan is fine and tiny. `dim_company` has 7,917 rows in one row group; the profiled plan (sequential scan with an ILIKE filter, Top-N 25 with late materialisation over a semi-join on rowid) reports a total execution time of 3.1 ms warm and 4.2 ms cold inside the engine (`company_search.warm.txt`, `company_search.cold.txt`). No index would change that. To split the remaining ~550 ms between page-cache cold reads and something else, I ran a bisection where each line is a fresh process: a **literal** ILIKE scan of the same table as the first statement costs 1.4 ms, a literal ORDER BY/LIMIT 2.4 ms, `SELECT 1` 0.3 ms, so reading `dim_company` from disk into an empty buffer pool is worth about 1 ms and the OS page cache contributes essentially nothing (the file was warm in the OS cache in every run, as the method states). Every variant containing a **`$1` parameter** costs 617 to 744 ms the first time, including `SELECT $1::INT` with the parameter `1`, which touches no table at all; after that first parameterised statement the full company_search takes 2.4 to 3.8 ms. `sys.modules` diffing shows what the first parameter bind does: DuckDB's Python bindings import `pandas` (and with it `numpy`, `pyarrow`, `dateutil`, ...) lazily to type-check parameter values. Pre-importing `numpy` alone leaves a 520 ms first call; pre-importing `pandas` (558 ms on its own) leaves a 3.4 ms first call. **Root cause: 100 % of the cold/warm gap is a one-time, per-process lazy `import pandas` inside DuckDB's parameter binding; page cache ~1 ms, plan ~3 to 4 ms.** Two consequences matter for honesty. First, the dashboard process never paid this cost, because Streamlit imports pandas before the first query runs; the 554 ms was a property of the benchmark's cold process, not of anything a user saw. Second, the cost cannot be removed while parameters are bound through the Python API; it can only be moved to a place where it is paid once and reported as such (change 02).

### sector_percentile: not a bad plan, an over-fetch plus per-request pandas work

The plan is a sequential scan of `fact_ratios` (1,184,079 rows; zone maps and the filters `basis = 'FY'`, `value IS NOT NULL` leave 72,095 rows), a hash join to the 2,716 Manufacturing companies (dynamic filter pushed into the scan), then an ORDER BY of the 70,912 surviving rows. The engine reports 37.9 ms warm for that (`sector_percentile.warm.txt`); a probe of `execute()` without fetching measured 21 ms. The benchmark measures `fetchall()`, which converts those 70,912 rows, including a `VARCHAR[]` column (`source_adshs`), into Python tuples and lists: 130 ms in the same probe, and the dashboard's `.df()` path 160 to 340 ms. The dashboard then reduced the 70,912 rows in pandas to the latest FY value per (company, ratio), about 28,000 rows, and computed the percentile rank and the yearly medians on every request. The warm-phase instability in section 1a has the same origin: with Python's cyclic garbage collector disabled, 50 warm runs of the original query measure p50 108 ms in the same process where they measure 224 ms with it enabled; the collector is triggered by the tens of thousands of container objects each `fetchall()` allocates, and its cost depends on the heap the process has accumulated. **Root cause: the query fetches the full FY history with a list column for a page that needs one row per company per ratio, and the aggregate (percentile, median) is recomputed per request in pandas.** An index would not help: the join key filter is already a dynamic filter on a hash join against 2,716 rows, and the scan cost is 21 ms of a 115 to 235 ms total.

### The three fast queries (regression guards)

`company_ratio_trend` (filter `cik = $1` on `fact_ratios`, 208 rows, engine 2.8 to 9.5 ms), `multi_company_compare` (`list_contains($1, cik)`, engine 10.7 to 17.1 ms) and `dq_summary` (22 rows plus one count over `restatements`, 3.9 ms) are zone-map sequential scans; they were left alone and benchmarked after every change.

## 3. Changes, one at a time

Each block is one code change followed by a full harness run; "before" is the measurement it was applied on top of. Reverted changes stay in the table. Threshold for "moved": at least 15 % and at least 1 ms of p50.

| change | kept | metric moved (>= 15% and >= 1 ms) | before (ms) | after (ms) | delta | not moved |
|---|---|---|---:|---:|---:|---|
| 02 eager `import pandas` in `db.connect()` | yes | company_search cold p50 | 630.3 | 3.6 | -626.7 (-99%) | company_ratio_trend, multi_company_compare, sector_percentile, dq_summary |
|  |  | connect p50 | 20.8 | 681.0 | +660.2 (+3175%) |  |
| 03 sector query: drop ORDER BY | no (reverted) | multi_company_compare warm p50 | 8.4 | 10.4 | +2.0 (+24%) | company_search, company_ratio_trend, dq_summary |
|  |  | sector_percentile warm p50 | 226.3 | 280.4 | +54.1 (+24%) |  |
| 04 sector query: drop `source_adshs` list column | no (reverted) | sector_percentile cold p50 | 132.3 | 78.9 | -53.4 (-40%) | company_search, company_ratio_trend, multi_company_compare, dq_summary |
|  |  | sector_percentile warm p50 | 226.3 | 125.2 | -101.1 (-45%) |  |
|  |  | dashboard load cold | 3,081.6 | failed | app error (column still referenced) |  |
|  |  | dashboard load warm | 1,787.2 | failed | app error (column still referenced) |  |
| 05 precomputed `sector_ratio_latest` / `sector_ratio_yearly` (+ app change) | yes | sector_percentile cold p50 | 132.3 | 27.7 | -104.7 (-79%) | company_search, company_ratio_trend, multi_company_compare, dq_summary |
|  |  | sector_percentile warm p50 | 226.3 | 41.7 | -184.5 (-82%) |  |
|  |  | process_wall p50 | 1,200.3 | 987.2 | -213.1 (-18%) |  |
|  |  | dashboard load cold | 3,081.6 | 2,367.5 | -714.1 (-23%) |  |
| 06 sector query: drop unused `industry`, `n_lower` columns | yes | sector_percentile cold p50 | 27.7 | 21.7 | -5.9 (-21%) | company_search, company_ratio_trend, multi_company_compare, dq_summary |
|  |  | sector_percentile warm p50 | 41.7 | 33.0 | -8.7 (-21%) |  |
| 07 ART index on `fact_ratios(cik)` | no (reverted) | company_ratio_trend cold p50 | 9.2 | 24.6 | +15.4 (+168%) | company_search, sector_percentile, dq_summary |
|  |  | company_ratio_trend warm p50 | 6.2 | 21.1 | +14.9 (+238%) |  |
|  |  | multi_company_compare warm p50 | 8.4 | 10.2 | +1.8 (+22%) |  |

Notes per change:

- **02 eager `import pandas` in `db.connect()`** (kept). One line. company_search cold p50 630.3 to 3.6 ms; the cost reappears as connection open p50 20.8 to 681.0 ms, once per process. Process wall-clock did not move (1,155.8 to 1,200.3 ms, within the control spread). This is a cost *moved and labelled*, not a cost removed, and it never affected the dashboard (section 2).
- **03 drop ORDER BY** (reverted). Warm sector p50 got worse, 226.3 to 280.4 ms. Without the sort the result is emitted as parallel chunks and the `fetchall()` materialisation got slower in this process; the ORDER BY was not the problem.
- **04 drop the `source_adshs` list column** (reverted as a standalone change). The query-level effect is real, cold 132.3 to 78.9 ms and warm 226.3 to 125.2 ms, which quantifies the list-column share of the cost, but the Sector tab still read that column and the dashboard load measurement failed. Superseded by 05, which moves the source lookup to a per-company query.
- **05 precomputed `sector_ratio_latest` and `sector_ratio_yearly`** (kept). Built at the end of `edgar-fundamentals ratios` by `ratios/sector.py`: one row per (company, ratio) with the latest FY value, `n_companies`, `n_lower` and `pct_rank = n_lower / n_companies` (strictly-lower count, ties in the denominator, exactly the old pandas expression), and one row per (sector, ratio, fiscal_year) with the median. The Sector tab reads these plus a two-column `SECTOR_FOCUS_SOURCES` query for the focus company's accession numbers. Sector cold 132.3 to 27.7 ms, warm 226.3 to 41.7 ms; dashboard cold load 3.08 to 2.37 s in the same-day sequence.
- **06 narrower projection** (kept): the query still returned `industry` and `n_lower`, which the tab does not display. Cold 27.7 to 21.7 ms, warm 41.7 to 33.0 ms.
- **07 ART index on `fact_ratios(cik)`** (reverted). The optimizer did use it (`bench/plans/experiments/company_ratio_trend.with_art_index.warm.txt`: "Type: Index Scan", engine 15.0 ms) and it was slower than the zone-map sequential scan (3.1 ms): company_ratio_trend cold 9.2 to 24.6 ms, warm 6.2 to 21.1 ms. Index build 0.3 s. Dropped.
- **Considered and not applied**: converting dashboard DataFrames through Arrow instead of `.df()`. After change 05 a probe showed at most 3 ms difference per query and it changes the `period_end` dtype the page relies on. Indexes on `dim_company` were not attempted: 7,917 rows, 3 ms plan.

## 4. Final before/after, identical harness

`bench/results/99_final.json`, plans in `bench/plans/after/`. Positive "saved"/"reduction" means faster than the frozen baseline; negative means slower.

| query | phase | baseline p50 | same-day control p50 (no code change) | final p50 | saved vs baseline (ms) | reduction | baseline p95 | final p95 | saved (ms) | reduction |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `company_search` | cold | 554.5 | 630.3 | 3.4 | +551.1 | +99.4% | 614.0 | 3.7 | +610.2 | +99.4% |
| `company_search` | warm | 2.4 | 4.1 | 4.2 | -1.9 | -79.8% | 2.5 | 6.2 | -3.6 | -143.8% |
| `company_ratio_trend` | cold | 8.8 | 9.1 | 8.8 | +0.0 | +0.4% | 10.2 | 11.2 | -1.0 | -10.2% |
| `company_ratio_trend` | warm | 3.7 | 6.4 | 6.2 | -2.6 | -71.2% | 4.4 | 8.4 | -4.0 | -91.0% |
| `multi_company_compare` | cold | 7.0 | 7.2 | 7.2 | -0.2 | -2.2% | 8.3 | 8.3 | +0.1 | +1.0% |
| `multi_company_compare` | warm | 4.5 | 9.6 | 9.8 | -5.3 | -117.1% | 5.2 | 13.4 | -8.3 | -160.7% |
| `sector_percentile` | cold | 125.1 | 131.2 | 21.8 | +103.3 | +82.6% | 132.0 | 23.2 | +108.8 | +82.4% |
| `sector_percentile` | warm | 115.1 | 235.6 | 33.6 | +81.5 | +70.8% | 125.8 | 39.4 | +86.4 | +68.6% |
| `dq_summary` | cold | 2.9 | 2.9 | 2.9 | +0.0 | +1.0% | 3.3 | 3.2 | +0.1 | +1.7% |
| `dq_summary` | warm | 1.6 | 2.9 | 2.9 | -1.3 | -80.1% | 1.7 | 4.3 | -2.7 | -159.0% |
| connection open (p50) | cold | 18.8 | 20.8 | 614.7 | -595.9 | -3170.6% | | | | |
| whole cold process: interpreter + imports + connect + 5 queries (p50) | cold | 1,041.0 | 1,155.8 | 981.5 | +59.5 | +5.7% | | | | |

How to read the negative rows: every warm p50 of the three fast queries and of company_search is 1.3 to 5.3 ms slower than the frozen baseline **and equal, to within 0.2 ms, to the same-day control with no code change** (company_search 4.1 vs 4.2, trend 6.4 vs 6.2, compare 9.6 vs 9.8, dq_summary 2.9 vs 2.9). The cold p50s of the three guards are unchanged against both references (8.8/9.1/8.8; 7.0/7.2/7.2; 2.9/2.9/2.9). So: no regression attributable to the code; the warm-phase offset is the day. The connection-open row is the moved pandas import, shown rather than hidden. The two claims that survive both references are company_search cold (554.5 and 630.3 to 3.4 ms) and sector_percentile (cold 125.1 and 131.2 to 21.8 ms; warm 115.1 and 235.6 to 33.6 ms).

## 5. Dashboard load

| dashboard load (server-side AppTest run) | baseline | same-day control (no code change) | final | saved vs baseline | reduction |
|---|---:|---:|---:|---:|---:|
| cold | 2.55 s | 3.62 s | 2.60 s | -0.04 s | -1.6% |
| warm | 0.88 s | 1.84 s | 1.62 s | -0.75 s | -85.6% |

Against the frozen baseline the dashboard did not improve (cold -0.04 s, warm 0.75 s slower); against the same-day control it is 1.0 s faster cold and 0.2 s faster warm, and the per-change table attributes -0.71 s cold to change 05. I do not claim a dashboard-load improvement from this pass: the number is dominated by Streamlit rendering and by machine state on the day (the control re-runs moved it by more than the code did), and the second-run "warm" figure is served from `st.cache_data`, so it measures rendering, not queries.

## 6. What the speed-up cost

Measured in `bench/results/cost_accounting.json`, `cost_sector_tables.json`, `cost_index.json`.

- **Eager pandas import** (change 02): `import pandas` measured 790, 793 and 813 ms in three fresh processes at the time of the cost run (558 to 640 ms earlier in the day; it is a heavy import and varies with the machine). It is paid once per process by every command that opens the warehouse, including `ingest` and `build`, which did not need pandas before (under 1.5 % of their 57 s and 84 s). The benchmark shows it as connection open p50 18.8 to 614.7 ms; whole-process wall-clock is unchanged (1,041.0 baseline, 1,155.8 control, 981.5 final).
- **Precomputed sector tables** (changes 05 and 06): `sector_ratio_latest` 58,456 rows in 7 storage blocks and `sector_ratio_yearly` 733 rows in 1 block, at 256 KiB per block = 2.0 MiB, 0.1 % of the 1.83 GiB file. The file size did not change (1,962,946,560 bytes before and after) because DuckDB reused free blocks left by earlier `CREATE OR REPLACE` builds; 162 free blocks remain. Build time: 0.14, 0.14 and 0.18 s per run, added to the `ratios` step. **Staleness: both tables are refreshed only when `edgar-fundamentals ratios` (or `all`) runs. They are exactly as fresh as `fact_ratios`, which is built by the same command, and like every other table in the file they are stale between builds; nothing recomputes them per request.** If `fact_ratios` were ever rebuilt by another path, the sector tables would silently lag it; the equivalence tests in section 7 would catch that.
- **What did not change**: the ratio values, the (cik, period_end, basis, ratio) grain of `fact_ratios`, the percentile definition, the median definition, and every other dashboard query's SQL. The original sector SQL is kept as `SECTOR_PERCENTILE_V0` and used by the tests.
- **Tried and paid for nothing**: the ART index cost 0.3 s to build and tripled `company_ratio_trend`; it is gone.

## 7. Tests: the optimized path returns identical answers

- `tests/test_sector_precompute.py` (in-memory DuckDB, synthetic data with ties, nulls, a stale year and a Q-basis row): the precomputed tables reproduce a reference implementation that is the *original* dashboard pandas code verbatim (`tests/reference_sector.py`): same company set, same values, same period_end and fiscal_year, same percentile under ties, same yearly medians including the even-count interpolation.
- `tests/test_optimization_equivalence.py` (real warehouse; Apple in Manufacturing, Microsoft in Services, JPMorgan in Finance, Insurance & Real Estate; all 13 ratios): `SECTOR_PERCENTILE_V0` plus the reference pandas logic against the optimized query and tables: identical company set per (sector, ratio), bit-identical values, identical periods, percentile ranks equal to 1e-12, yearly medians equal to 1e-9, focus-company source accession numbers equal to the `fact_ratios` rows, and the unchanged trend/compare/search queries still pinned to the hand-computed FY2024 fixtures. One deliberate display difference is asserted explicitly: the old expander listed ratios the focus company had no value for with a `None` percentile; the new table omits those rows.
- `tests/test_bench_tools.py`: the report renders from the saved results with the sign conventions shown above; plan capture writes cold and warm files.

pytest: **104 passed**, 0 failed, 0 errors, 0 skipped (104 collected; the baseline had 89). Line coverage of `edgar_fundamentals` (excluding the Streamlit page script): **72.6%** (1,109 of 1,528 statements; the baseline was 71.3% of 1,325).

## 8. Limitations

- One machine, one day, desktop hardware with other applications open; no isolation of cores, no repeated days.
- The OS page cache was never dropped, so "cold" means a cold DuckDB buffer pool and a fresh Python process, not cold storage.
- The warm baseline numbers could not be reproduced on the day of the pass with no code change (section 1a); the sector warm number in particular is sensitive to Python garbage-collector state. Per-change deltas are same-day; the frozen-baseline comparison is shown with the same-day control beside it.
- The query mix is synthetic: five fixed statements with fixed parameters ("micro", Apple, five large caps, Manufacturing), not real user traffic; p50 over 20 cold runs has a resolution of a few milliseconds at best.
- The company_search improvement is a cost moved into connection set-up and labelled; dashboard users never experienced the 554 ms.
- Dashboard load is measured server side through AppTest, without a browser, and its warm figure is cache-served rendering time.

## 9. Reproduce

```
uv run edgar-fundamentals plans --out bench/plans/before           # plans + bisection
uv run edgar-fundamentals bench --out bench/results/NN_change.json  # full harness after each change
uv run edgar-fundamentals ratios                                    # rebuilds fact_ratios and the sector tables
uv run python -m edgar_fundamentals.bench.write_optimization_md     # this document
uv run pytest -q                                                    # equivalence tests
```
