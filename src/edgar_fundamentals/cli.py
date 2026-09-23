"""Command-line entry point: edgar-fundamentals <command>."""
from __future__ import annotations

import argparse
import json
import sys
import time

from edgar_fundamentals import config
from edgar_fundamentals.log import get_logger

log = get_logger("edgar.cli")


def cmd_ingest(args) -> None:
    from edgar_fundamentals.ingest import download, load, manifest

    quarters = [str(q) for q in config.quarters(args.quarters, args.latest)]
    log.info("ingest window: %s", ", ".join(quarters))
    t0 = time.perf_counter()
    results = download.download_all(quarters, force=args.force)
    for r in results:
        lr = load.load_quarter(r.quarter, zip_path=r.path, force=args.force, drop_extracted=args.drop_extracted)
        e = manifest.get(r.quarter)
        log.info("%s summary: zip=%s bytes (%s), rows=%s, download=%.1fs, extract=%.1fs, parse=%.1fs, %s rows/s",
                 r.quarter, f"{r.bytes_total:,}", "cached" if r.cached else "downloaded",
                 f"{lr.total_rows:,}", e.get("download_seconds", 0.0), lr.extract_seconds, lr.parse_seconds,
                 f"{lr.rows_per_second:,.0f}")
    log.info("ingest finished in %.1fs", time.perf_counter() - t0)


def cmd_build(args) -> None:
    from edgar_fundamentals.warehouse import aliases, runner

    problems = aliases.check_aliases()
    if problems:
        for p in problems:
            log.error("aliases.yaml: %s", p)
        sys.exit(2)
    runner.build()


def cmd_validate(args) -> None:
    from edgar_fundamentals.quality import report, runner

    runner.run_all()
    d = report.write()
    log.info("data quality: %d rules, overall pass rate %.4f%%, report -> %s",
             d["rules_implemented"], 100 * (d["overall_pass_rate"] or 0), config.path("reports_dir") / "data_quality.md")


def cmd_ratios(args) -> None:
    from edgar_fundamentals.ratios import compute

    compute.build_ratio_table()


def cmd_bench(args) -> None:
    import shutil

    from edgar_fundamentals.bench import run

    run.run_benchmarks(cold_runs=args.cold_runs, warm_runs=args.warm_runs)
    if getattr(args, "out", None):
        dst = config.PROJECT_ROOT / args.out
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(config.path("reports_dir") / "bench.json", dst)
        log.info("bench result copied -> %s", dst)


def cmd_plans(args) -> None:
    from edgar_fundamentals.bench import plans

    out = config.PROJECT_ROOT / args.out
    plans.save_plans(out)
    if not args.no_bisect:
        plans.bisect_company_search(out)


def cmd_metrics(args) -> None:
    from edgar_fundamentals.metrics import collect

    m = collect.write_metrics(run_tests=not args.no_tests)
    print(collect.summary_text(m))


def cmd_screenshots(args) -> None:
    from edgar_fundamentals.dashboard import screenshots

    screenshots.capture()


def cmd_all(args) -> None:
    cmd_ingest(args)
    cmd_build(args)
    cmd_validate(args)
    cmd_ratios(args)
    cmd_bench(args)
    cmd_metrics(args)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="edgar-fundamentals",
                                description="SEC Financial Statement Data Sets -> DuckDB warehouse, quality, ratios.")
    sub = p.add_subparsers(dest="command", required=True)

    def add_ingest_args(sp):
        sp.add_argument("--quarters", type=int, default=None, help="number of quarters (default from settings)")
        sp.add_argument("--latest", default=None, help="latest quarter, e.g. 2026q2")
        sp.add_argument("--force", action="store_true", help="re-download and re-parse even if cached")
        sp.add_argument("--drop-extracted", action="store_true", help="delete extracted txt files after parsing")

    def add_bench_args(sp):
        sp.add_argument("--cold-runs", type=int, default=20)
        sp.add_argument("--warm-runs", type=int, default=50)
        sp.add_argument("--out", default=None, help="also copy reports/bench.json to this path (e.g. bench/results/02_x.json)")

    def add_metrics_args(sp):
        sp.add_argument("--no-tests", action="store_true", help="skip running pytest for the coverage numbers")

    sp = sub.add_parser("ingest", help="download and parse the quarterly ZIPs into Parquet"); add_ingest_args(sp)
    sp.set_defaults(func=cmd_ingest)
    sp = sub.add_parser("build", help="build the DuckDB warehouse from Parquet"); sp.set_defaults(func=cmd_build)
    sp = sub.add_parser("validate", help="run all data-quality rules and write the report"); sp.set_defaults(func=cmd_validate)
    sp = sub.add_parser("ratios", help="compute the ratio layer"); sp.set_defaults(func=cmd_ratios)
    sp = sub.add_parser("bench", help="benchmark the dashboard queries"); add_bench_args(sp); sp.set_defaults(func=cmd_bench)
    sp = sub.add_parser("plans", help="save EXPLAIN ANALYZE plans (cold/warm) and the company_search bisection")
    sp.add_argument("--out", default="bench/plans/before"); sp.add_argument("--no-bisect", action="store_true")
    sp.set_defaults(func=cmd_plans)
    sp = sub.add_parser("metrics", help="write METRICS.md"); add_metrics_args(sp); sp.set_defaults(func=cmd_metrics)
    sp = sub.add_parser("screenshots", help="capture dashboard screenshots with Playwright"); sp.set_defaults(func=cmd_screenshots)
    sp = sub.add_parser("all", help="ingest -> build -> validate -> ratios -> bench -> metrics")
    add_ingest_args(sp); add_bench_args(sp); add_metrics_args(sp); sp.set_defaults(func=cmd_all)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
