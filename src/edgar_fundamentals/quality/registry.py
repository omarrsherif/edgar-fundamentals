"""Rule registry: every file in quality/rules/*.sql is one named data-quality rule.

A rule file starts with a metadata header:

    -- id: R01
    -- name: balance_sheet_identity
    -- category: identity
    -- severity: error
    -- unit: company-period (balance sheet date)
    -- description: ...

followed by a SELECT that yields one row per evaluated unit (or aggregated rows) with columns:
    status   'pass' | 'fail' | 'skip'   (required)
    n        row weight, default 1       (optional; lets a rule return "pass, 12,345,678" as one row)
    cik, adsh, period_end, qtrs, tag, observed, expected, diff, message   (optional detail columns)

Thresholds are injected as ${name} placeholders from config/quality_rules.yaml.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from edgar_fundamentals import config

RESULT_COLUMNS: dict[str, str] = {
    "status": "VARCHAR", "n": "BIGINT", "cik": "BIGINT", "adsh": "VARCHAR", "period_end": "DATE",
    "qtrs": "INTEGER", "tag": "VARCHAR", "observed": "DOUBLE", "expected": "DOUBLE", "diff": "DOUBLE",
    "message": "VARCHAR",
}

HEADER_RE = re.compile(r"^--\s*(\w+)\s*:\s*(.*?)\s*$")


@dataclass(frozen=True)
class Rule:
    id: str
    name: str
    category: str
    severity: str
    unit: str
    description: str
    sql: str
    path: Path


def parse_rule(path: Path) -> Rule:
    meta: dict[str, str] = {}
    body: list[str] = []
    in_header = True
    for line in path.read_text(encoding="utf-8").splitlines():
        if in_header:
            m = HEADER_RE.match(line.strip())
            if m and m.group(1) in {"id", "name", "category", "severity", "unit", "description"}:
                meta[m.group(1)] = m.group(2)
                continue
            if line.strip() == "" or line.strip().startswith("--"):
                continue
            in_header = False
        body.append(line)
    missing = {"id", "name", "category", "severity", "unit", "description"} - set(meta)
    if missing:
        raise ValueError(f"{path.name}: missing header fields {sorted(missing)}")
    return Rule(meta["id"], meta["name"], meta["category"], meta["severity"], meta["unit"],
                meta["description"], "\n".join(body).strip().rstrip(";"), path)


def load_rules(rules_dir: Path | None = None) -> list[Rule]:
    rules_dir = rules_dir or config.RULES_DIR
    rules = [parse_rule(p) for p in sorted(rules_dir.glob("*.sql"))]
    ids = [r.id for r in rules]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate rule ids: {ids}")
    return rules


def rule_params(cfg: dict | None = None) -> dict[str, str]:
    """Placeholders available to rule SQL, rendered as SQL literals."""
    cfg = cfg or config.load_yaml("quality_rules.yaml")
    params = {k: repr(float(v)) if isinstance(v, float) else str(v) for k, v in cfg["tolerances"].items()}
    tags = []
    for t in cfg["non_negative_tags"]:
        taxonomy, name = (t.split(":", 1) if ":" in t else (None, t))
        tags.append(f"('{name}', {('NULL' if taxonomy is None else repr(taxonomy))})")
    params["non_negative_tags"] = ", ".join(tags)
    params["allowed_fp"] = ", ".join(repr(x) for x in cfg["allowed_fp"])
    return params
