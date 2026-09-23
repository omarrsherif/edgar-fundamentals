"""edgar-fundamentals Streamlit dashboard.

Run:  uv run streamlit run src/edgar_fundamentals/dashboard/app.py
Every figure and table carries the SEC accession number(s) it was computed from, linked to EDGAR.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from edgar_fundamentals import config, db
from edgar_fundamentals.dashboard import components as c
from edgar_fundamentals.dashboard import queries as q

st.set_page_config(page_title="edgar-fundamentals", page_icon=":bar_chart:", layout="wide")


@st.cache_resource
def get_connection():
    return db.connect(read_only=True)


@st.cache_data(ttl=600, show_spinner=False)
def run_query(sql: str, params: tuple) -> pd.DataFrame:
    # A cursor per call: DuckDB connections are not shared safely across Streamlit threads.
    cur = get_connection().cursor()
    try:
        return cur.execute(sql, list(params)).df()
    finally:
        cur.close()


def ratios_wide(df: pd.DataFrame) -> pd.DataFrame:
    return df.pivot_table(index=["period_end", "basis"], columns="ratio", values="value", aggfunc="first").reset_index()


# ------------------------------------------------------------------------------------ header
st.title("edgar-fundamentals")
st.caption("SEC Financial Statement Data Sets, 8 quarters, modelled in DuckDB. Every figure links to its source filing.")

tab_company, tab_compare, tab_sector, tab_dq, tab_about = st.tabs(
    ["Company", "Compare", "Sector", "Data quality", "About"])

# ------------------------------------------------------------------------------------ Company
with tab_company:
    col_a, col_b = st.columns([2, 3])
    with col_a:
        term = st.text_input("Search company name or CIK", value="Apple", key="search")
    hits = run_query(q.COMPANY_SEARCH, (term,)) if term else pd.DataFrame()
    if hits.empty:
        st.info("No company matches.")
    else:
        with col_b:
            label = hits.apply(lambda r: f"{r['name']} (CIK {r['cik']}, {r['industry']})", axis=1)
            pick = st.selectbox("Company", options=list(range(len(hits))), format_func=lambda i: label[i], key="pick")
        row = hits.iloc[pick]
        cik = int(row["cik"])
        st.subheader(f"{row['name']}")
        st.caption(f"CIK {cik} | SIC {row['sic']} | {row['sector']} / {row['industry']} | "
                   f"{row['n_in_scope_filings']} 10-K/10-Q filings, last filed {pd.Timestamp(row['last_filed']).date()}")

        trend = run_query(q.COMPANY_RATIO_TREND, (cik,))
        if trend.empty:
            st.warning("No ratios computed for this company.")
        else:
            basis = st.radio("Basis", ["FY", "Q"], horizontal=True, key="basis_company",
                             help="FY = annual flows; Q = standalone quarters (derived from year-to-date where needed)")
            t = trend[trend["basis"] == basis]
            latest_pe = pd.Timestamp(t["period_end"].max()).date()
            latest = t[pd.to_datetime(t["period_end"]).dt.date == latest_pe].set_index("ratio")
            st.markdown(f"**Latest {basis} period: {latest_pe}**")
            tiles = st.columns(6)
            for i, r in enumerate(["gross_margin", "operating_margin", "net_margin", "current_ratio", "debt_to_equity", "roe"]):
                if r in latest.index:
                    v, status, reason = latest.loc[r, ["value", "status", "reason"]]
                    tiles[i].metric(c.RATIO_LABELS[r], c.fmt_value(r, v), help=f"status: {status}" + (f" - {reason}" if reason else ""))
            src = [a for lst in latest["source_adshs"] for a in c.adsh_list(lst)]
            c.source_expander(cik, src, "Source filings for the latest period")

            st.markdown("#### Ratio trends")
            chosen = st.multiselect("Ratios", list(c.RATIO_LABELS), default=["gross_margin", "net_margin", "roe", "current_ratio"],
                                    format_func=lambda r: c.RATIO_LABELS[r], key="ratios_company")
            cols = st.columns(2)
            for i, r in enumerate(chosen):
                s = t[(t["ratio"] == r) & t["value"].notna()]
                if s.empty:
                    cols[i % 2].info(f"{c.RATIO_LABELS[r]}: no values - " + "; ".join(t[t['ratio'] == r]['reason'].dropna().unique()[:3]))
                    continue
                cols[i % 2].plotly_chart(c.line_chart(s, "period_end", "value", None, c.RATIO_LABELS[r], r),
                                         use_container_width=True, key=f"trend_{r}")

            st.markdown("#### All ratios with status, reason and source filings")
            show = t.copy()
            show["source_adshs"] = show["source_adshs"].apply(lambda l: ", ".join(c.adsh_list(l)))
            show["first_source_url"] = show["source_adshs"].apply(lambda s: c.edgar_url(cik, s.split(", ")[0]) if s else None)
            st.dataframe(show[["period_end", "fiscal_year", "fiscal_quarter", "ratio", "value", "status", "reason", "source_adshs", "first_source_url"]],
                         use_container_width=True, hide_index=True, height=320,
                         column_config={"first_source_url": c.link_col("EDGAR")})

            st.markdown("#### Normalized facts")
            facts = run_query(q.COMPANY_FACTS, (cik,))
            facts = c.with_links(facts.assign(cik=cik), "cik", "source_adsh")
            st.dataframe(facts.drop(columns=["cik"]), use_container_width=True, hide_index=True, height=320,
                         column_config={"source_url": c.link_col()})

            rest = run_query(q.COMPANY_RESTATEMENTS, (cik,))
            if not rest.empty:
                st.markdown(f"#### Restatements for this company ({len(rest)} versions)")
                rest = c.with_links(rest.assign(cik=cik), "cik", "adsh")
                st.dataframe(rest.drop(columns=["cik"]), use_container_width=True, hide_index=True, height=240,
                             column_config={"source_url": c.link_col("This version")})
            dq = run_query(q.COMPANY_DQ, (cik,))
            if not dq.empty:
                st.markdown(f"#### Data-quality findings for this company ({len(dq)})")
                dq = c.with_links(dq.assign(cik=cik), "cik", "adsh")
                st.dataframe(dq.drop(columns=["cik"]), use_container_width=True, hide_index=True, height=240,
                             column_config={"source_url": c.link_col()})

# ------------------------------------------------------------------------------------ Compare
with tab_compare:
    st.markdown("Compare up to 8 companies on one ratio (fixed colour per company).")
    term2 = st.text_input("Add companies by name or CIK", value="", key="search2")
    options = st.session_state.setdefault("compare_ciks", {320193: "APPLE INC.", 789019: "MICROSOFT CORP"})
    if term2:
        found = run_query(q.COMPANY_SEARCH, (term2,))
        for _, r in found.head(8).iterrows():
            if st.button(f"+ {r['name']} ({r['cik']})", key=f"add_{r['cik']}"):
                options[int(r["cik"])] = r["name"]
    selected = st.multiselect("Companies", list(options), default=list(options)[:8], format_func=lambda k: f"{options[k]} ({k})",
                              key="compare_sel", max_selections=8)
    basis2 = st.radio("Basis", ["FY", "Q"], horizontal=True, key="basis_compare")
    ratio2 = st.selectbox("Ratio", list(c.RATIO_LABELS), format_func=lambda r: c.RATIO_LABELS[r], key="ratio_compare")
    if selected:
        cmp = run_query(q.MULTI_COMPANY_COMPARE, (selected, basis2))
        s = cmp[(cmp["ratio"] == ratio2) & cmp["value"].notna()]
        if s.empty:
            st.info("No values for that ratio.")
        else:
            st.plotly_chart(c.line_chart(s, "period_end", "value", "name", c.RATIO_LABELS[ratio2], ratio2),
                            use_container_width=True, key="compare_chart")
            latest = s.sort_values("period_end").groupby("cik").tail(1)
            latest = latest.assign(value_fmt=[c.fmt_value(ratio2, v) for v in latest["value"]],
                                   first_source=[(c.adsh_list(l) or [None])[0] for l in latest["source_adshs"]])
            latest = c.with_links(latest, "cik", "first_source")
            st.dataframe(latest[["name", "cik", "period_end", "value_fmt", "status", "first_source", "source_url"]],
                         use_container_width=True, hide_index=True, column_config={"source_url": c.link_col()})
            with st.expander("Side by side: all ratios, latest period"):
                allr = cmp[cmp["value"].notna()].sort_values("period_end").groupby(["cik", "ratio"]).tail(1)
                wide = allr.pivot_table(index="name", columns="ratio", values="value", aggfunc="first")
                st.dataframe(wide.style.format(precision=3), use_container_width=True)

# ------------------------------------------------------------------------------------ Sector
with tab_sector:
    sectors = run_query(q.SECTORS, ())
    sector = st.selectbox("Sector (SIC division)", sectors["sector"], key="sector",
                          format_func=lambda s: f"{s} ({int(sectors.set_index('sector').loc[s, 'n'])} companies)")
    ratio3 = st.selectbox("Ratio", list(c.RATIO_LABELS), index=2, format_func=lambda r: c.RATIO_LABELS[r], key="ratio_sector")
    # One row per (company, ratio): latest FY value and its percentile rank, precomputed by `edgar-fundamentals ratios`.
    sec = run_query(q.SECTOR_PERCENTILE, (sector,))
    latest = sec[sec["ratio"] == ratio3]
    if latest.empty:
        st.info("No data.")
    else:
        names = latest.sort_values("name")
        focus = st.selectbox("Company to rank within the sector", names["cik"], key="focus",
                             format_func=lambda k: names.set_index("cik").loc[k, "name"])
        frow = latest.set_index("cik").loc[focus]
        fv, pct = float(frow["value"]), float(frow["pct_rank"])
        colA, colB = st.columns([3, 2])
        with colA:
            st.plotly_chart(c.histogram_with_marker(latest["value"], fv, f"{c.RATIO_LABELS[ratio3]}: latest FY value per company",
                                                    ratio3, f"{frow['name']}: {c.fmt_value(ratio3, fv)}"),
                            use_container_width=True, key="sector_hist")
        with colB:
            st.metric("Percentile within sector", f"{pct:.0%}",
                      help=f"share of the {int(frow['n_companies'])} sector companies with a lower latest value")
            qs = latest["value"].quantile([0.1, 0.25, 0.5, 0.75, 0.9])
            st.dataframe(pd.DataFrame({"percentile": ["p10", "p25", "p50", "p75", "p90"],
                                       "value": [c.fmt_value(ratio3, v) for v in qs]}), hide_index=True)
            src = run_query(q.SECTOR_FOCUS_SOURCES, (int(focus),))
            src_list = [a for lst in src[src["ratio"] == ratio3]["source_adshs"] for a in c.adsh_list(lst)]
            c.source_expander(int(focus), src_list, "Focus company source filings")
        med = run_query(q.SECTOR_MEDIAN_TREND, (sector,))
        med = med[med["ratio"] == ratio3][["fiscal_year", "median_value"]].rename(columns={"median_value": "value"})
        med["fiscal_year"] = med["fiscal_year"].astype(str)
        st.plotly_chart(c.line_chart(med, "fiscal_year", "value", None, f"Sector median {c.RATIO_LABELS[ratio3]} by fiscal year", ratio3),
                        use_container_width=True, key="sector_trend")
        with st.expander("Percentile table for every ratio (latest FY value per company)"):
            tbl = sec[sec["cik"] == focus][["ratio", "pct_rank", "n_companies"]].rename(
                columns={"pct_rank": "percentile", "n_companies": "companies"}).sort_values("ratio")
            st.dataframe(tbl, hide_index=True, use_container_width=True)

# ------------------------------------------------------------------------------------ Data quality
with tab_dq:
    summ = run_query(q.DQ_SUMMARY, ())
    if summ.empty:
        st.info("Run `edgar-fundamentals validate` first.")
    else:
        total_eval, total_fail = int(summ["evaluated"].sum()), int(summ["failed"].sum())
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Rules", len(summ))
        k2.metric("Units evaluated", f"{total_eval:,}")
        k3.metric("Overall pass rate", f"{1 - total_fail / total_eval:.3%}")
        k4.metric("Restatements detected", f"{int(summ['restatement_groups'].iloc[0]):,}")
        st.plotly_chart(c.bar_chart(summ, "rule_name", "failure_rate", "Failure rate per rule (colour = severity: red error, yellow warn, blue info)",
                                    color_by_severity=summ["severity"]), use_container_width=True, key="dq_bar")
        st.dataframe(summ[["rule_id", "rule_name", "category", "severity", "unit", "evaluated", "passed", "failed", "skipped",
                           "failure_rate", "coverage", "description"]],
                     use_container_width=True, hide_index=True,
                     column_config={"failure_rate": st.column_config.NumberColumn(format="%.4f"),
                                    "coverage": st.column_config.NumberColumn(format="%.3f")})
        rule_pick = st.selectbox("Drill into a rule", summ["rule_name"], key="rule_pick")
        fails = run_query(q.DQ_FAILURES, (rule_pick,))
        if fails.empty:
            st.success("No failures for this rule.")
        else:
            fails = c.with_links(fails, "cik", "adsh")
            st.dataframe(fails, use_container_width=True, hide_index=True, height=320, column_config={"source_url": c.link_col()})
        st.markdown("#### Largest restatements (earlier value vs authoritative later filing)")
        top = run_query(q.TOP_RESTATEMENTS, ())
        top = c.with_links(top, "cik", "earlier_adsh", "earlier_url")
        top = c.with_links(top, "cik", "authoritative_adsh", "authoritative_url")
        st.dataframe(top, use_container_width=True, hide_index=True, height=360,
                     column_config={"earlier_url": c.link_col("Earlier filing"), "authoritative_url": c.link_col("Authoritative filing")})

# ------------------------------------------------------------------------------------ About
with tab_about:
    metrics_path = config.PROJECT_ROOT / "METRICS.md"
    if metrics_path.exists():
        st.markdown(metrics_path.read_text(encoding="utf-8"))
    else:
        st.info("METRICS.md not generated yet (run `edgar-fundamentals metrics`).")
    st.markdown("Conventions: fiscal year = calendar year in which the fiscal year ends; balance-sheet ratios use ending "
                "balances; quarterly returns are unannualized; consolidated (non-dimensional) facts only.")
