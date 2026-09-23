"""Reference implementation of the ORIGINAL Sector-tab logic (pre-optimization dashboard code, verbatim
semantics) used to prove the precomputed sector tables return identical answers."""
from __future__ import annotations

import pandas as pd


def latest_per_company(sec: pd.DataFrame, ratio: str) -> pd.DataFrame:
    """app.py (v0): sr = sec[sec.ratio == ratio]; latest = sr.sort_values('period_end').groupby('cik').tail(1)"""
    sr = sec[sec["ratio"] == ratio]
    return sr.sort_values("period_end").groupby("cik").tail(1)


def percentile(latest: pd.DataFrame, focus_cik: int) -> float:
    """app.py (v0): fv = latest.set_index('cik').loc[focus, 'value']; pct = (latest['value'] < fv).mean()"""
    fv = float(latest.set_index("cik").loc[focus_cik, "value"])
    return float((latest["value"] < fv).mean())


def yearly_median(sec: pd.DataFrame, ratio: str) -> pd.Series:
    """app.py (v0): med = sr.groupby('fiscal_year')['value'].median()"""
    sr = sec[sec["ratio"] == ratio]
    return sr.groupby("fiscal_year")["value"].median()


def percentile_table(sec: pd.DataFrame, focus_cik: int) -> pd.DataFrame:
    """app.py (v0) 'Percentile table for every ratio' expander, verbatim."""
    allr = sec.sort_values("period_end").groupby(["cik", "ratio"]).tail(1)
    rank = allr.groupby("ratio")["value"].apply(
        lambda s: (s < float(allr[(allr["cik"] == focus_cik) & (allr["ratio"] == s.name)]["value"].iloc[0])).mean()
        if ((allr["cik"] == focus_cik) & (allr["ratio"] == s.name)).any() else None)
    return pd.DataFrame({"ratio": rank.index, "percentile": rank.values,
                         "companies": allr.groupby("ratio")["cik"].nunique().reindex(rank.index).values})
