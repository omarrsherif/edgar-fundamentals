"""Render the tables of bench/OPTIMIZATION.md from the saved benchmark results in bench/results/.

Every number in the report's tables comes from these JSON files (each one a full run of the unchanged
harness: 20 cold runs, 50 warm runs after 5 warm-ups, p50/p95 via bench.run.pct). Nothing is transcribed
by hand.  Usage:  uv run python -m edgar_fundamentals.bench.optimization_report
"""
from __future__ import annotations

import json

from edgar_fundamentals import config

RESULTS = config.PROJECT_ROOT / "bench" / "results"
QUERIES = ["company_search", "company_ratio_trend", "multi_company_compare", "sector_percentile", "dq_summary"]

# (file stem, label, kept?, file stem of the measurement this change is compared against = the state it was applied to)
CHANGES = [
    ("02_eager_pandas_import", "02 eager `import pandas` in `db.connect()`", True, "01b_control_rerun2"),
    ("03_sector_drop_order_by", "03 sector query: drop ORDER BY", False, "02_eager_pandas_import"),
    ("04_sector_drop_list_column", "04 sector query: drop `source_adshs` list column", False, "02_eager_pandas_import"),
    ("05_sector_precomputed_table", "05 precomputed `sector_ratio_latest` / `sector_ratio_yearly` (+ app change)", True, "02_eager_pandas_import"),
    ("06_sector_narrower_projection", "06 sector query: drop unused `industry`, `n_lower` columns", True, "05_sector_precomputed_table"),
    ("07_art_index_fact_ratios_cik", "07 ART index on `fact_ratios(cik)`", False, "06_sector_narrower_projection"),
]


def load(stem: str) -> dict | None:
    p = RESULTS / f"{stem}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def f1(x) -> str:
    return "n/a" if x is None else f"{x:,.1f}"


def delta(a, b) -> str:
    if a is None or b is None:
        return "n/a"
    d = b - a
    return f"{d:+,.1f} ({d / a * 100:+.0f}%)" if a else f"{d:+,.1f}"


def noise_table(baseline: dict, controls: list[tuple[str, dict]]) -> str:
    lines = ["| run | " + " | ".join(f"{q} cold p50 / warm p50" for q in QUERIES) + " | dashboard cold / warm (s) |",
             "|---|" + "---:|" * (len(QUERIES) + 1)]
    for label, r in [("baseline (frozen)", baseline)] + controls:
        cells = [f"{f1(r['queries'][q]['cold_p50_ms'])} / {f1(r['queries'][q]['warm_p50_ms'])}" for q in QUERIES]
        d = r["dashboard"]
        cells.append(f"{d['cold_ms'] / 1000:.2f} / {d['warm_ms'] / 1000:.2f}" if d.get("cold_ms") else "n/a")
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def per_change_table() -> str:
    lines = ["| change | kept | metric moved (>= 15% and >= 1 ms) | before (ms) | after (ms) | delta | not moved |",
             "|---|---|---|---:|---:|---:|---|"]
    for stem, label, kept, base_stem in CHANGES:
        r, base = load(stem), load(base_stem)
        if r is None or base is None:
            continue
        kept_s = "yes" if kept else "no (reverted)"
        moved = []
        for q in QUERIES:
            for phase in ("cold", "warm"):
                a, b = base["queries"][q][f"{phase}_p50_ms"], r["queries"][q][f"{phase}_p50_ms"]
                if a and abs(b - a) / a >= 0.15 and abs(b - a) >= 1.0:
                    moved.append((f"{q} {phase} p50", a, b))
        for k in ("connect_p50_ms", "process_wall_p50_ms"):
            a, b = base[k], r[k]
            if a and abs(b - a) / a >= 0.15:
                moved.append((k.replace("_p50_ms", " p50"), a, b))
        for phase in ("cold", "warm"):
            a, b = base["dashboard"].get(f"{phase}_ms"), r["dashboard"].get(f"{phase}_ms")
            if a and b and abs(b - a) / a >= 0.15:
                moved.append((f"dashboard load {phase}", a, b))
            elif a and not b:
                moved.append((f"dashboard load {phase}", a, None))
        unmoved = [q for q in QUERIES if not any(m[0].startswith(q) for m in moved)]
        first = True
        for name, a, b in moved or [("(nothing moved >= 15%)", None, None)]:
            after = "failed" if (b is None and a is not None) else f1(b)
            d = "app error (column still referenced)" if (b is None and a is not None) else delta(a, b)
            lines.append(f"| {label if first else ''} | {kept_s if first else ''} | {name} | {f1(a)} | {after} | {d} | "
                         f"{', '.join(unmoved) if first else ''} |")
            first = False
    return "\n".join(lines)


def final_table(before: dict, after: dict, control: dict | None = None) -> str:
    """Positive 'saved' / 'reduction' = faster than the frozen baseline; negative = slower."""
    lines = ["| query | phase | baseline p50 | same-day control p50 (no code change) | final p50 | saved vs baseline (ms) | reduction | baseline p95 | final p95 | saved (ms) | reduction |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for q in QUERIES:
        for phase in ("cold", "warm"):
            b50, a50 = before["queries"][q][f"{phase}_p50_ms"], after["queries"][q][f"{phase}_p50_ms"]
            c50 = control["queries"][q][f"{phase}_p50_ms"] if control else None
            b95, a95 = before["queries"][q][f"{phase}_p95_ms"], after["queries"][q][f"{phase}_p95_ms"]
            lines.append(f"| `{q}` | {phase} | {f1(b50)} | {f1(c50)} | {f1(a50)} | {b50 - a50:+,.1f} | {(b50 - a50) / b50 * 100:+.1f}% | "
                         f"{f1(b95)} | {f1(a95)} | {b95 - a95:+,.1f} | {(b95 - a95) / b95 * 100:+.1f}% |")
    for key, label in (("connect_p50_ms", "connection open (p50)"),
                       ("process_wall_p50_ms", "whole cold process: interpreter + imports + connect + 5 queries (p50)")):
        b, a, c = before[key], after[key], (control[key] if control else None)
        lines.append(f"| {label} | cold | {f1(b)} | {f1(c)} | {f1(a)} | {b - a:+,.1f} | {(b - a) / b * 100:+.1f}% | | | | |")
    return "\n".join(lines)


def dashboard_table(before: dict, after: dict, control: dict | None = None) -> str:
    lines = ["| dashboard load (server-side AppTest run) | baseline | same-day control (no code change) | final | saved vs baseline | reduction |",
             "|---|---:|---:|---:|---:|---:|"]
    for phase in ("cold", "warm"):
        b, a = before["dashboard"][f"{phase}_ms"], after["dashboard"][f"{phase}_ms"]
        c = control["dashboard"][f"{phase}_ms"] if control else None
        lines.append(f"| {phase} | {b / 1000:.2f} s | {f'{c / 1000:.2f} s' if c else 'n/a'} | {a / 1000:.2f} s | {(b - a) / 1000:+.2f} s | {(b - a) / b * 100:+.1f}% |")
    return "\n".join(lines)


def render() -> str:
    baseline, final = load("00_baseline"), load("99_final")
    controls = [(f"control re-run {i} (no code change)", r) for i, r in
                enumerate([load("01_control_rerun"), load("01b_control_rerun2")], 1) if r]
    parts = ["### Noise floor: the unchanged harness re-run before any change\n", noise_table(baseline, controls),
             "\n### Per-change deltas (one change per block, full harness, compared with the measurement it was applied on top of)\n",
             per_change_table()]
    if final:
        control = load("01b_control_rerun2")
        parts += ["\n### Final before/after (frozen baseline vs final, identical harness; same-day control shown for scale)\n",
                  final_table(baseline, final, control), "\n", dashboard_table(baseline, final, control)]
    return "\n".join(parts) + "\n"


if __name__ == "__main__":
    print(render())
