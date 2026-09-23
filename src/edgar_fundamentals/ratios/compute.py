"""Ratio layer.

Pure functions (unit-tested directly) take a dict of canonical-metric inputs and return a RatioResult
whose value is None with an explicit reason whenever an input is missing or a denominator is not usable.
`build_ratio_table` assembles the inputs from fact_normalized (FY basis: annual flows; Q basis: quarterly
flows, derived from year-to-date values when a standalone quarter was not filed) and writes fact_ratios.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from typing import Callable

import duckdb

from edgar_fundamentals import config, db
from edgar_fundamentals.log import get_logger

log = get_logger("edgar.ratios")

INSTANT_METRICS = [
    "total_assets", "current_assets", "current_liabilities", "total_liabilities", "equity_parent",
    "inventory", "short_term_borrowings", "ltd_current", "ltd_noncurrent",
]
FLOW_METRICS = [
    "revenue", "cost_of_revenue", "gross_profit", "operating_income", "net_income",
    "operating_cash_flow", "capex",
]


@dataclass(frozen=True)
class Input:
    value: float
    adsh: str
    tag: str
    status: str = "reported"      # reported | derived | derived_from_ytd

    def as_dict(self) -> dict:
        return {"value": self.value, "adsh": self.adsh, "tag": self.tag, "status": self.status}


@dataclass
class RatioResult:
    value: float | None
    status: str                   # ok | derived | estimated | null
    reason: str
    inputs: dict[str, Input] = field(default_factory=dict)

    @property
    def source_adshs(self) -> list[str]:
        seen: list[str] = []
        for i in self.inputs.values():
            for a in i.adsh.split("+"):
                if a and a not in seen:
                    seen.append(a)
        return seen


Inputs = dict[str, Input | None]


def _null(reason: str, **used: Input) -> RatioResult:
    return RatioResult(None, "null", reason, {k: v for k, v in used.items() if v is not None})


def _ok(value: float, used: dict[str, Input], status: str = "ok", reason: str = "") -> RatioResult:
    if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
        return RatioResult(None, "null", "non_finite_result", used)
    if status == "ok" and any(i.status != "reported" for i in used.values()):
        status = "derived"
        reason = reason or "uses_derived_input:" + ",".join(k for k, i in used.items() if i.status != "reported")
    return RatioResult(float(value), status, reason, used)


def _missing(inputs: Inputs, *names: str) -> list[str]:
    return [n for n in names if inputs.get(n) is None]


def gross_margin(i: Inputs) -> RatioResult:
    rev = i.get("revenue")
    if rev is None:
        return _null("missing:revenue")
    if rev.value == 0:
        return _null("zero_denominator:revenue", revenue=rev)
    gp, cogs = i.get("gross_profit"), i.get("cost_of_revenue")
    if gp is not None:
        return _ok(gp.value / rev.value, {"revenue": rev, "gross_profit": gp})
    if cogs is not None:
        return _ok((rev.value - cogs.value) / rev.value, {"revenue": rev, "cost_of_revenue": cogs})
    return _null("missing:gross_profit|cost_of_revenue", revenue=rev)


def operating_margin(i: Inputs) -> RatioResult:
    m = _missing(i, "operating_income", "revenue")
    if m:
        return _null("missing:" + "|".join(m))
    rev, oi = i["revenue"], i["operating_income"]
    if rev.value == 0:
        return _null("zero_denominator:revenue", revenue=rev, operating_income=oi)
    return _ok(oi.value / rev.value, {"operating_income": oi, "revenue": rev})


def net_margin(i: Inputs) -> RatioResult:
    m = _missing(i, "net_income", "revenue")
    if m:
        return _null("missing:" + "|".join(m))
    rev, ni = i["revenue"], i["net_income"]
    if rev.value == 0:
        return _null("zero_denominator:revenue", revenue=rev, net_income=ni)
    return _ok(ni.value / rev.value, {"net_income": ni, "revenue": rev})


def current_ratio(i: Inputs) -> RatioResult:
    m = _missing(i, "current_assets", "current_liabilities")
    if m:
        return _null("missing:" + "|".join(m))
    ca, cl = i["current_assets"], i["current_liabilities"]
    if cl.value == 0:
        return _null("zero_denominator:current_liabilities", current_assets=ca, current_liabilities=cl)
    return _ok(ca.value / cl.value, {"current_assets": ca, "current_liabilities": cl})


def quick_ratio(i: Inputs) -> RatioResult:
    m = _missing(i, "current_assets", "current_liabilities")
    if m:
        return _null("missing:" + "|".join(m))
    ca, cl, inv = i["current_assets"], i["current_liabilities"], i.get("inventory")
    if cl.value == 0:
        return _null("zero_denominator:current_liabilities", current_assets=ca, current_liabilities=cl)
    used = {"current_assets": ca, "current_liabilities": cl}
    if inv is None:
        return _ok(ca.value / cl.value, used, status="estimated", reason="assumes_zero:inventory")
    used["inventory"] = inv
    return _ok((ca.value - inv.value) / cl.value, used)


def debt_to_equity(i: Inputs) -> RatioResult:
    eq = i.get("equity_parent")
    if eq is None:
        return _null("missing:equity_parent")
    comps = {k: i.get(k) for k in ("short_term_borrowings", "ltd_current", "ltd_noncurrent")}
    present = {k: v for k, v in comps.items() if v is not None}
    if not present:
        return _null("missing:short_term_borrowings|ltd_current|ltd_noncurrent", equity_parent=eq)
    if eq.value <= 0:
        return _null("non_positive_equity", equity_parent=eq, **present)
    debt = sum(v.value for v in present.values())
    used = {"equity_parent": eq, **present}
    assumed = [k for k, v in comps.items() if v is None]
    if assumed:
        return _ok(debt / eq.value, used, status="estimated", reason="assumes_zero:" + ",".join(assumed))
    return _ok(debt / eq.value, used)


def liabilities_to_equity(i: Inputs) -> RatioResult:
    m = _missing(i, "total_liabilities", "equity_parent")
    if m:
        return _null("missing:" + "|".join(m))
    tl, eq = i["total_liabilities"], i["equity_parent"]
    if eq.value <= 0:
        return _null("non_positive_equity", total_liabilities=tl, equity_parent=eq)
    return _ok(tl.value / eq.value, {"total_liabilities": tl, "equity_parent": eq})


def roa(i: Inputs) -> RatioResult:
    m = _missing(i, "net_income", "total_assets")
    if m:
        return _null("missing:" + "|".join(m))
    ni, ta = i["net_income"], i["total_assets"]
    if ta.value <= 0:
        return _null("non_positive_denominator:total_assets", net_income=ni, total_assets=ta)
    return _ok(ni.value / ta.value, {"net_income": ni, "total_assets": ta})


def roe(i: Inputs) -> RatioResult:
    m = _missing(i, "net_income", "equity_parent")
    if m:
        return _null("missing:" + "|".join(m))
    ni, eq = i["net_income"], i["equity_parent"]
    if eq.value <= 0:
        return _null("non_positive_equity", net_income=ni, equity_parent=eq)
    return _ok(ni.value / eq.value, {"net_income": ni, "equity_parent": eq})


def asset_turnover(i: Inputs) -> RatioResult:
    m = _missing(i, "revenue", "total_assets")
    if m:
        return _null("missing:" + "|".join(m))
    rev, ta = i["revenue"], i["total_assets"]
    if ta.value <= 0:
        return _null("non_positive_denominator:total_assets", revenue=rev, total_assets=ta)
    return _ok(rev.value / ta.value, {"revenue": rev, "total_assets": ta})


def free_cash_flow(i: Inputs) -> RatioResult:
    m = _missing(i, "operating_cash_flow", "capex")
    if m:
        return _null("missing:" + "|".join(m))
    ocf, capex = i["operating_cash_flow"], i["capex"]
    return _ok(ocf.value - capex.value, {"operating_cash_flow": ocf, "capex": capex})


def working_capital(i: Inputs) -> RatioResult:
    m = _missing(i, "current_assets", "current_liabilities")
    if m:
        return _null("missing:" + "|".join(m))
    ca, cl = i["current_assets"], i["current_liabilities"]
    return _ok(ca.value - cl.value, {"current_assets": ca, "current_liabilities": cl})


def yoy_revenue_growth(i: Inputs) -> RatioResult:
    rev = i.get("revenue")
    if rev is None:
        return _null("missing:revenue")
    prior = i.get("revenue_prior_year")
    if prior is None:
        return _null("prior_period_not_found", revenue=rev)
    if prior.value <= 0:
        return _null("non_positive_prior_revenue", revenue=rev, revenue_prior_year=prior)
    return _ok(rev.value / prior.value - 1, {"revenue": rev, "revenue_prior_year": prior})


RATIOS: dict[str, Callable[[Inputs], RatioResult]] = {
    "gross_margin": gross_margin,
    "operating_margin": operating_margin,
    "net_margin": net_margin,
    "current_ratio": current_ratio,
    "quick_ratio": quick_ratio,
    "debt_to_equity": debt_to_equity,
    "liabilities_to_equity": liabilities_to_equity,
    "roa": roa,
    "roe": roe,
    "asset_turnover": asset_turnover,
    "free_cash_flow": free_cash_flow,
    "working_capital": working_capital,
    "yoy_revenue_growth": yoy_revenue_growth,
}


def compute_all(inputs: Inputs) -> dict[str, RatioResult]:
    return {name: fn(inputs) for name, fn in RATIOS.items()}


# ---------------------------------------------------------------------------------------------
# Assembling inputs from the warehouse
# ---------------------------------------------------------------------------------------------

RATIO_INPUTS_SQL = """
CREATE OR REPLACE TABLE ratio_inputs AS
WITH n AS (
  SELECT cik, period_end, qtrs, metric, value, source_adsh, source_tag, status, currency, fiscal_year, fiscal_quarter
  FROM fact_normalized
  WHERE metric IN ({all_metrics})
),
instants AS (
  SELECT cik, period_end, metric, value, source_adsh, source_tag, status, currency, fiscal_year, fiscal_quarter
  FROM n WHERE qtrs = 0 AND metric IN ({instant_metrics})
),
fy_flows AS (
  SELECT cik, period_end, metric, value, source_adsh, source_tag, status, currency, fiscal_year, fiscal_quarter
  FROM n WHERE qtrs = 4 AND metric IN ({flow_metrics})
),
q_direct AS (
  SELECT cik, period_end, metric, value, source_adsh, source_tag, status, currency, fiscal_year, fiscal_quarter
  FROM n WHERE qtrs = 1 AND metric IN ({flow_metrics})
),
q_derived AS (
  SELECT a.cik, a.period_end, a.metric, a.value - b.value AS value,
         a.source_adsh || '+' || b.source_adsh AS source_adsh,
         'ytd' || a.qtrs || '(' || a.source_tag || ')-ytd' || b.qtrs AS source_tag,
         'derived_from_ytd' AS status, a.currency, a.fiscal_year, a.fiscal_quarter
  FROM n a
  JOIN n b ON b.cik = a.cik AND b.metric = a.metric AND b.qtrs = a.qtrs - 1
          AND b.period_end = last_day((a.period_end - to_months(3))::DATE)
  WHERE a.qtrs IN (2, 3, 4) AND a.metric IN ({flow_metrics})
  QUALIFY row_number() OVER (PARTITION BY a.cik, a.period_end, a.metric ORDER BY a.qtrs) = 1
),
q_flows AS (
  SELECT * FROM q_direct
  UNION ALL
  SELECT d.* FROM q_derived d
  ANTI JOIN q_direct q ON q.cik = d.cik AND q.period_end = d.period_end AND q.metric = d.metric
),
fy_periods AS (SELECT DISTINCT cik, period_end FROM fy_flows),
q_periods AS (SELECT DISTINCT cik, period_end FROM q_flows),
fy_rows AS (
  SELECT 'FY' AS basis, * FROM fy_flows
  UNION ALL
  SELECT 'FY', i.* FROM instants i JOIN fy_periods USING (cik, period_end)
),
q_rows AS (
  SELECT 'Q' AS basis, * FROM q_flows
  UNION ALL
  SELECT 'Q', i.* FROM instants i JOIN q_periods USING (cik, period_end)
),
all_rows AS (SELECT * FROM fy_rows UNION ALL SELECT * FROM q_rows),
prior AS (
  SELECT r.basis, r.cik, r.period_end, 'revenue_prior_year' AS metric, p.value, p.source_adsh, p.source_tag,
         p.status, p.currency, r.fiscal_year, r.fiscal_quarter
  FROM all_rows r
  JOIN all_rows p ON p.basis = r.basis AND p.cik = r.cik AND p.metric = 'revenue'
                 AND p.period_end BETWEEN last_day((r.period_end - to_months(13))::DATE)
                                      AND last_day((r.period_end - to_months(11))::DATE)
  WHERE r.metric = 'revenue'
  QUALIFY row_number() OVER (PARTITION BY r.basis, r.cik, r.period_end
                             ORDER BY abs(date_diff('day', p.period_end, last_day((r.period_end - to_months(12))::DATE)))) = 1
)
SELECT * FROM all_rows
UNION ALL
SELECT * FROM prior
"""


def build_ratio_table(con: duckdb.DuckDBPyConnection | None = None) -> dict:
    own = con is None
    con = con or db.connect()
    t0 = time.perf_counter()
    try:
        all_metrics = ", ".join(f"'{m}'" for m in INSTANT_METRICS + FLOW_METRICS)
        con.execute(RATIO_INPUTS_SQL.format(
            all_metrics=all_metrics,
            instant_metrics=", ".join(f"'{m}'" for m in INSTANT_METRICS),
            flow_metrics=", ".join(f"'{m}'" for m in FLOW_METRICS),
        ))
        n_inputs = db.row_count(con, "ratio_inputs")
        log.info("ratio_inputs: %s rows (%.1fs)", f"{n_inputs:,}", time.perf_counter() - t0)

        rows = con.execute("""
            SELECT basis, cik, period_end, any_value(fiscal_year), any_value(fiscal_quarter), any_value(currency),
                   list(metric), list(value), list(source_adsh), list(source_tag), list(status)
            FROM ratio_inputs
            GROUP BY basis, cik, period_end
        """).fetchall()

        cols = {k: [] for k in ("cik", "period_end", "basis", "fiscal_year", "fiscal_quarter", "ratio", "value",
                                "status", "reason", "inputs_json", "source_adshs", "currency")}
        for basis, cik, period_end, fy, fq, currency, metrics, values, adshs, tags, statuses in rows:
            inputs: Inputs = {
                m: Input(float(v), a, t, s) for m, v, a, t, s in zip(metrics, values, adshs, tags, statuses)
                if v is not None
            }
            for name, res in compute_all(inputs).items():
                for k, v in zip(cols, (cik, period_end, basis, fy, fq, name, res.value, res.status, res.reason,
                                       json.dumps({ik: iv.as_dict() for ik, iv in res.inputs.items()}),
                                       res.source_adshs, currency)):
                    cols[k].append(v)
        log.info("computed %s ratio rows in Python (%.1fs)", f"{len(cols['cik']):,}", time.perf_counter() - t0)
        import pyarrow as pa

        table = pa.table({
            "cik": pa.array(cols["cik"], pa.int64()), "period_end": pa.array(cols["period_end"], pa.date32()),
            "basis": pa.array(cols["basis"], pa.string()), "fiscal_year": pa.array(cols["fiscal_year"], pa.int32()),
            "fiscal_quarter": pa.array(cols["fiscal_quarter"], pa.int32()), "ratio": pa.array(cols["ratio"], pa.string()),
            "value": pa.array(cols["value"], pa.float64()), "status": pa.array(cols["status"], pa.string()),
            "reason": pa.array(cols["reason"], pa.string()), "inputs_json": pa.array(cols["inputs_json"], pa.string()),
            "source_adshs": pa.array(cols["source_adshs"], pa.list_(pa.string())),
            "currency": pa.array(cols["currency"], pa.string()),
        })
        con.register("ratio_rows_arrow", table)
        con.execute("CREATE OR REPLACE TABLE fact_ratios AS SELECT * FROM ratio_rows_arrow")
        con.unregister("ratio_rows_arrow")
        stats = con.execute("""
            SELECT count(*) AS rows, count(*) FILTER (WHERE value IS NOT NULL) AS non_null,
                   count(DISTINCT cik) AS companies, count(DISTINCT (cik, period_end, basis)) AS company_periods
            FROM fact_ratios
        """).fetchone()
        seconds = time.perf_counter() - t0
        log.info("fact_ratios: %s rows, %s non-null, %s companies, %s company-periods (%.1fs)",
                 f"{stats[0]:,}", f"{stats[1]:,}", f"{stats[2]:,}", f"{stats[3]:,}", seconds)
        from edgar_fundamentals.ratios import sector

        sector_stats = sector.build_sector_tables(con)  # precomputed Sector-tab aggregates (bench/OPTIMIZATION.md)
        return {"rows": stats[0], "non_null": stats[1], "companies": stats[2], "company_periods": stats[3],
                "seconds": seconds, "sector_tables": sector_stats}
    finally:
        if own:
            con.close()
