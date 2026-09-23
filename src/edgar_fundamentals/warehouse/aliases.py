"""Load config/aliases.yaml and config/sic_sectors.yaml into DuckDB lookup tables, and apply derivations."""
from __future__ import annotations

import re

import duckdb

from edgar_fundamentals import config


def parse_tag(tag: str) -> tuple[str | None, str]:
    """'dei:EntityCommonStockSharesOutstanding' -> ('dei', 'EntityCommonStockSharesOutstanding')."""
    if ":" in tag:
        prefix, name = tag.split(":", 1)
        return prefix, name
    return None, tag


def alias_rows(aliases: dict | None = None) -> list[tuple]:
    aliases = aliases or config.load_yaml("aliases.yaml")
    rows = []
    for metric, spec in aliases["metrics"].items():
        for priority, tag in enumerate(spec["tags"], start=1):
            taxonomy, name = parse_tag(tag)
            rows.append((metric, name, taxonomy, priority, spec["datatype"], spec.get("statement")))
    return rows


def check_aliases(aliases: dict | None = None) -> list[str]:
    """Return a list of problems (empty when the YAML is consistent)."""
    aliases = aliases or config.load_yaml("aliases.yaml")
    problems = []
    seen: dict[str, str] = {}
    for metric, spec in aliases["metrics"].items():
        if spec.get("datatype") not in {"monetary", "shares", "perShare", "pure"}:
            problems.append(f"{metric}: unknown datatype {spec.get('datatype')}")
        if not spec.get("tags"):
            problems.append(f"{metric}: no tags")
        for tag in spec.get("tags", []):
            if tag in seen and seen[tag] != metric:
                # A tag may appear under two metrics only for the basic-and-diluted combined concepts.
                if not tag.endswith("BasicAndDiluted"):
                    problems.append(f"tag {tag} mapped to both {seen[tag]} and {metric}")
            seen[tag] = metric
    metrics = set(aliases["metrics"])
    for d in aliases.get("derivations", []):
        if d["metric"] not in metrics:
            problems.append(f"derivation for unknown metric {d['metric']}")
        for sign, term in parse_formula(d["formula"]):
            if term not in metrics:
                problems.append(f"derivation {d['metric']} references unknown metric {term}")
    return problems


def parse_formula(formula: str) -> list[tuple[int, str]]:
    """'+a -b +c' -> [(1,'a'), (-1,'b'), (1,'c')]"""
    out = []
    for m in re.finditer(r"([+-])\s*([A-Za-z_][A-Za-z0-9_]*)", formula):
        out.append((1 if m.group(1) == "+" else -1, m.group(2)))
    return out


def create_alias_table(con: duckdb.DuckDBPyConnection, aliases: dict | None = None) -> None:
    con.execute("CREATE OR REPLACE TABLE alias_map (canonical_metric VARCHAR, tag VARCHAR, taxonomy VARCHAR, "
                "priority INTEGER, datatype VARCHAR, statement VARCHAR)")
    con.executemany("INSERT INTO alias_map VALUES (?, ?, ?, ?, ?, ?)", alias_rows(aliases))


def create_sic_table(con: duckdb.DuckDBPyConnection, sectors: dict | None = None) -> None:
    sectors = sectors or config.load_yaml("sic_sectors.yaml")
    con.execute("CREATE OR REPLACE TABLE sic_sector_map (sic_from INTEGER, sic_to INTEGER, division VARCHAR, "
                "major_group INTEGER, industry VARCHAR)")
    divisions = sectors["divisions"]
    rows = []
    for mg, name in sectors["major_groups"].items():
        mg = int(mg)
        lo, hi = mg * 100, mg * 100 + 99
        division = next((d["name"] for d in divisions if d["from"] <= lo <= d["to"]), "Unknown")
        rows.append((lo, hi, division, mg, name))
    con.executemany("INSERT INTO sic_sector_map VALUES (?, ?, ?, ?, ?)", rows)
    con.execute("CREATE OR REPLACE TABLE financial_sic_ranges (sic_from INTEGER, sic_to INTEGER)")
    con.executemany("INSERT INTO financial_sic_ranges VALUES (?, ?)",
                    [(lo, hi) for lo, hi in sectors.get("financial_sic_ranges", [])])


def apply_derivations(con: duckdb.DuckDBPyConnection, aliases: dict | None = None) -> dict[str, int]:
    """Insert derived rows into fact_normalized for company-periods lacking a reported value."""
    aliases = aliases or config.load_yaml("aliases.yaml")
    inserted: dict[str, int] = {}
    for d in aliases.get("derivations", []):
        metric = d["metric"]
        terms = parse_formula(d["formula"])
        optional = set(d.get("optional", []))
        required = [t for _, t in terms if t not in optional]
        term_names = [t for _, t in terms]
        pivots = ",\n      ".join(f"max(CASE WHEN metric = '{t}' THEN value END) AS {t}" for t in term_names)
        expr = " + ".join(
            f"({sign}) * {'coalesce(' + t + ', 0)' if t in optional else t}" for sign, t in terms
        )
        required_not_null = " AND ".join(f"{t} IS NOT NULL" for t in required) or "TRUE"
        datatype = aliases["metrics"][metric]["datatype"]
        sql = f"""
        INSERT INTO fact_normalized
        WITH p AS (
          SELECT cik, period_end, qtrs,
            any_value(period_key) AS period_key, any_value(fiscal_year) AS fiscal_year, any_value(fiscal_quarter) AS fiscal_quarter,
            any_value(currency) AS currency, any_value(uom) AS uom,
            arg_max(source_adsh, source_filed) AS source_adsh, max(source_filed) AS source_filed,
            arg_max(source_form, source_filed) AS source_form,
            count(DISTINCT source_adsh) AS n_sources, bool_or(is_restated) AS is_restated,
            {pivots}
          FROM fact_normalized
          WHERE metric IN ({", ".join("'" + t + "'" for t in term_names)})
          GROUP BY cik, period_end, qtrs
        )
        SELECT p.cik, p.period_end, p.period_key, p.qtrs, p.fiscal_year, p.fiscal_quarter,
          '{metric}' AS metric, '{datatype}' AS datatype,
          {expr} AS value, p.uom, p.currency, p.source_adsh,
          'derived:{d["formula"]}' AS source_tag, 99 AS alias_rank, p.source_filed, p.source_form,
          0 AS n_candidates, p.n_sources, 1 AS n_distinct_values, p.is_restated,
          'derived' AS status, '{d["reason"]}' AS resolution_reason
        FROM p
        WHERE {required_not_null}
          AND NOT EXISTS (SELECT 1 FROM fact_normalized h WHERE h.metric = '{metric}'
                          AND h.cik = p.cik AND h.period_end = p.period_end AND h.qtrs = p.qtrs)
        """
        before = con.execute("SELECT count(*) FROM fact_normalized").fetchone()[0]
        con.execute(sql)
        after = con.execute("SELECT count(*) FROM fact_normalized").fetchone()[0]
        inserted[metric] = after - before
    return inserted
