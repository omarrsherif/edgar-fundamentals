"""Shared dashboard pieces: palette, EDGAR links, chart factories."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Categorical palette in fixed order (validated light-mode set from the dataviz reference palette).
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
TEXT_PRIMARY, TEXT_SECONDARY, GRID = "#0b0b0b", "#52514e", "#e6e5e1"

RATIO_LABELS = {
    "gross_margin": "Gross margin", "operating_margin": "Operating margin", "net_margin": "Net margin",
    "current_ratio": "Current ratio", "quick_ratio": "Quick ratio", "debt_to_equity": "Debt / equity",
    "liabilities_to_equity": "Liabilities / equity", "roa": "Return on assets", "roe": "Return on equity",
    "asset_turnover": "Asset turnover", "free_cash_flow": "Free cash flow", "working_capital": "Working capital",
    "yoy_revenue_growth": "YoY revenue growth",
}
PERCENT_RATIOS = {"gross_margin", "operating_margin", "net_margin", "roa", "roe", "yoy_revenue_growth"}
CURRENCY_RATIOS = {"free_cash_flow", "working_capital"}


def adsh_list(x) -> list[str]:
    """DuckDB returns VARCHAR[] columns as numpy arrays / lists / None; normalise to a list of strings."""
    if x is None:
        return []
    try:
        if pd.isna(x):
            return []
    except (TypeError, ValueError):
        pass
    return [str(a) for a in list(x) if a]


def edgar_url(cik: int, adsh: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{adsh.replace('-', '')}/{adsh}-index.htm"


def link_col(label: str = "Source filing"):
    return st.column_config.LinkColumn(label, display_text=r"([0-9-]+)-index\.htm$")


def with_links(df: pd.DataFrame, cik_col: str, adsh_col: str, out_col: str = "source_url") -> pd.DataFrame:
    df = df.copy()
    df[out_col] = [edgar_url(c, a) if isinstance(a, str) and a else None for c, a in zip(df[cik_col], df[adsh_col])]
    return df


def fmt_value(ratio: str, v) -> str:
    if v is None or pd.isna(v):
        return "n/a"
    if ratio in PERCENT_RATIOS:
        return f"{v:.1%}"
    if ratio in CURRENCY_RATIOS:
        return f"{v / 1e9:,.2f} B"
    return f"{v:.2f}"


def base_layout(title: str, yfmt: str | None = None, height: int = 300) -> dict:
    return dict(
        title=dict(text=title, font=dict(size=14, color=TEXT_PRIMARY), x=0),
        height=height, margin=dict(l=8, r=8, t=40, b=8),
        plot_bgcolor="white", paper_bgcolor="white",
        font=dict(color=TEXT_SECONDARY, size=12),
        xaxis=dict(showgrid=False, zeroline=False, linecolor=GRID),
        yaxis=dict(gridcolor=GRID, zeroline=False, tickformat=yfmt),
        legend=dict(orientation="h", y=-0.2, font=dict(color=TEXT_SECONDARY)),
        hovermode="x unified",
    )


def line_chart(df: pd.DataFrame, x: str, y: str, series: str | None, title: str, ratio: str) -> go.Figure:
    yfmt = ".0%" if ratio in PERCENT_RATIOS else (".2s" if ratio in CURRENCY_RATIOS else ".2f")
    fig = go.Figure()
    groups = [(None, df)] if series is None else list(df.groupby(series, sort=False))
    for i, (name, g) in enumerate(groups):
        fig.add_trace(go.Scatter(
            x=g[x], y=g[y], mode="lines+markers", name=str(name) if name is not None else RATIO_LABELS.get(ratio, ratio),
            line=dict(width=2, color=PALETTE[i % len(PALETTE)]), marker=dict(size=8),
            hovertemplate="%{x|%b %Y}: %{y:" + yfmt + "}<extra>%{fullData.name}</extra>",
        ))
    fig.update_layout(**base_layout(title, yfmt))
    fig.update_layout(showlegend=series is not None)
    return fig


def histogram_with_marker(values: pd.Series, marker: float | None, title: str, ratio: str, marker_label: str) -> go.Figure:
    lo, hi = values.quantile(0.05), values.quantile(0.95)
    clipped = values.clip(lo, hi)  # tails folded into the edge bins so the bulk of the sector stays readable
    title = f"{title} (tails clipped at p5/p95)"
    fig = go.Figure(go.Histogram(x=clipped, nbinsx=40, marker=dict(color=PALETTE[0], line=dict(color="white", width=1)),
                                 hovertemplate="%{x}: %{y} companies<extra></extra>"))
    if marker is not None and not pd.isna(marker):
        fig.add_vline(x=max(min(marker, hi), lo), line=dict(color=PALETTE[1], width=2),
                      annotation_text=marker_label, annotation_position="top", annotation_font_color=TEXT_PRIMARY)
    yfmt = ".0%" if ratio in PERCENT_RATIOS else None
    lay = base_layout(title, None, 280)
    lay["xaxis"]["tickformat"] = yfmt
    lay["hovermode"] = "closest"
    fig.update_layout(**lay, showlegend=False, bargap=0.05)
    return fig


def bar_chart(df: pd.DataFrame, x: str, y: str, title: str, yfmt: str = ".1%", color_by_severity: pd.Series | None = None) -> go.Figure:
    colors = PALETTE[0]
    if color_by_severity is not None:
        sev_color = {"error": PALETTE[7], "warn": PALETTE[3], "info": PALETTE[0]}
        colors = [sev_color.get(s, PALETTE[0]) for s in color_by_severity]
    fig = go.Figure(go.Bar(x=df[x], y=df[y], marker=dict(color=colors, line=dict(color="white", width=1)),
                           hovertemplate="%{x}: %{y:" + yfmt + "}<extra></extra>"))
    lay = base_layout(title, yfmt, 320)
    lay["hovermode"] = "closest"
    lay["xaxis"]["tickangle"] = -35
    fig.update_layout(**lay, showlegend=False, bargap=0.25)
    return fig


def source_expander(cik: int, adshs: list[str], label: str = "Source filings") -> None:
    adshs = [a for a in dict.fromkeys(adshs) if a]
    with st.expander(f"{label} ({len(adshs)} accession numbers)"):
        for a in adshs:
            st.markdown(f"- [{a}]({edgar_url(cik, a)})")
