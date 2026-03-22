"""
frontend.pages.etf
==================
Page – ETF Screener.

Supports two display modes:

1. **ETF mode** ("All ETFs", Bonds, Real Estate, custom added ETFs):
   Shows ETF-level metrics — AUM, Expense Ratio, P/E, Dividend Yield, Returns.
   Period toggle switches between Quarterly (3M/6M) and Annual (1Y/3Y) returns.
   Data sourced from yfinance ETF info (5-min cache).

2. **Stock / Index mode** (S&P 500, Nasdaq-100, Total Market, Small Cap, International):
   Shows individual stock fundamentals for index constituents — same columns as
   the Stock Screener (Gross Margin, ROIC, FCF Margin, Score, P/E, P/B, etc.).
   Period toggle switches between Quarterly and Annual financial statements.
   Data sourced from the local database (pre-fetched financial statements).

Use the group dropdown to switch between groups/modes.
"""

from __future__ import annotations

import dash
import dash_ag_grid as dag
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, dcc, html

from frontend.api_client import (
    admin_fetch,
    admin_compute,
    admin_classify,
    admin_add_etf_ticker,
    admin_remove_etf_ticker,
    get_etf_groups,
    get_etf_screener,
    get_index_stocks,
)
from frontend.config import API_BASE_URL

dash.register_page(__name__, path="/etf", name="ETF Screener", title="ETF Screener")

# ---------------------------------------------------------------------------
# Static group order – used to sort dropdown options predictably
# ---------------------------------------------------------------------------

_ETF_MODE_KEYS   = ["all", "bonds", "realestate"]
_STOCK_MODE_KEYS = ["us_large", "us_growth", "us_total", "us_small", "intl"]
_STOCK_MODE_GROUPS = set(_STOCK_MODE_KEYS)

# Human-readable labels for predefined groups (fallback if API unreachable)
_STATIC_LABELS: dict[str, str] = {
    "all":        "All ETFs",
    "bonds":      "Bonds",
    "realestate": "Real Estate",
    "us_large":   "S&P 500",
    "us_growth":  "Nasdaq-100",
    "us_total":   "Total Market",
    "us_small":   "Small Cap",
    "intl":       "International",
}


def _is_custom_group(group: str, groups_store: dict) -> bool:
    """Return True if *group* is a custom-added ETF (not a predefined group)."""
    return bool((groups_store or {}).get(group, {}).get("custom", False))


def _build_dropdown_options(groups: dict) -> list[dict]:
    """Build ordered dropdown options from the /etf/groups API payload."""
    opts: list[dict] = []

    # Section header: ETF groups
    opts.append({"label": "── ETF Groups ──", "value": "__sep_etf__", "disabled": True})
    for key in _ETF_MODE_KEYS:
        if key in groups:
            opts.append({"label": groups[key]["label"], "value": key})

    # Section header: Index / stock groups
    opts.append({"label": "── Index Stocks (Top 100) ──", "value": "__sep_idx__", "disabled": True})
    for key in _STOCK_MODE_KEYS:
        if key in groups:
            opts.append({"label": groups[key]["label"], "value": key})

    # Custom-added ETFs (not in either predefined list)
    predefined = set(_ETF_MODE_KEYS + _STOCK_MODE_KEYS)
    custom_keys = [k for k, v in groups.items() if k not in predefined and v.get("custom")]
    if custom_keys:
        opts.append({"label": "── Custom / Added ETFs ──", "value": "__sep_custom__", "disabled": True})
        for key in sorted(custom_keys):
            opts.append({"label": groups[key]["label"], "value": key})

    return opts


# Default options (rendered before the API responds)
_DEFAULT_DROPDOWN_OPTIONS = _build_dropdown_options(
    {k: {"label": lbl, "tickers": [], "custom": False}
     for k, lbl in _STATIC_LABELS.items()}
)


# ---------------------------------------------------------------------------
# ETF mode column definitions – shared base
# ---------------------------------------------------------------------------

_ETF_COL_BASE = [
    {
        "field": "ticker",
        "headerName": "Ticker",
        "width": 100,
        "pinned": "left",
        "tooltipField": "description",
        "headerTooltip": "Hover over a ticker to read the ETF's full description.",
    },
    {
        "field": "name",
        "headerName": "ETF Name",
        "minWidth": 180,
        "flex": 2,
        "wrapText": True,
        "autoHeight": True,
    },
    {
        "field": "category",
        "headerName": "Category",
        "width": 130,
    },
    {
        "field": "expense_ratio",
        "headerName": "Exp. Ratio %",
        "width": 115,
        "type": "numericColumn",
        "headerTooltip": (
            "Expense Ratio = Annual Fund Costs / Average Net Assets\n\n"
            "The fee you pay every year just for holding the ETF.\n\n"
            "Benchmarks:\n"
            "- < 0.10%  →  ultra-low (Vanguard / iShares flagships)\n"
            "- 0.10–0.50%  →  reasonable for specialised strategies\n"
            "- > 0.50%  →  high for passive indexing; scrutinise the value-add"
        ),
        "valueFormatter": {"function": "params.value != null ? params.value.toFixed(2) + '%' : '—'"},
        "cellStyle": {
            "function": (
                "params.data.er_pass "
                "? {color: '#2ecc71', fontWeight: 600} "
                ": {color: '#e67e22', fontWeight: 600}"
            )
        },
    },
    {
        "field": "aum_b",
        "headerName": "AUM ($B)",
        "width": 105,
        "type": "numericColumn",
        "headerTooltip": (
            "Assets Under Management (billions USD)\n\n"
            "Larger AUM → tighter bid-ask spreads, lower tracking error.\n\n"
            "Tiers:\n"
            "- > $100B  →  flagship, extreme liquidity\n"
            "- $10B–$100B  →  highly liquid, institutional-grade\n"
            "- $1B–$10B  →  liquid enough for most retail investors\n"
            "- < $1B  →  watch for wider spreads and closure risk"
        ),
        "valueFormatter": {"function": "params.value != null ? '$' + params.value.toFixed(1) + 'B' : '—'"},
        "cellStyle": {
            "function": (
                "params.data.aum_pass "
                "? {color: '#2ecc71', fontWeight: 600} "
                ": {color: '#e67e22', fontWeight: 600}"
            )
        },
    },
    {
        "field": "pe_ratio",
        "headerName": "P/E",
        "width": 80,
        "type": "numericColumn",
        "headerTooltip": (
            "Aggregate P/E = Weighted-Average Price / Earnings of all holdings\n\n"
            "Benchmarks (equity ETFs):\n"
            "- < 15  →  historically cheap\n"
            "- 15–25  →  fair value range\n"
            "- > 30  →  elevated; priced for strong future growth"
        ),
        "valueFormatter": {"function": "params.value != null ? params.value.toFixed(1) : '—'"},
        "cellStyle": {
            "function": (
                "params.data.pe_pass "
                "? {color: '#2ecc71', fontWeight: 600} "
                ": {color: '#e67e22', fontWeight: 600}"
            )
        },
    },
    {
        "field": "dividend_yield",
        "headerName": "Div. Yield %",
        "width": 115,
        "type": "numericColumn",
        "headerTooltip": (
            "Dividend / Distribution Yield %\n"
            "= Annual Distributions / Current ETF Price × 100\n\n"
            "Typical ranges:\n"
            "- Growth equity (QQQ, VUG)  →  < 0.5%\n"
            "- Broad equity (SPY, VTI)  →  1–2%\n"
            "- Dividend-focused (VYM, SCHD)  →  3–4%\n"
            "- Bonds / REITs  →  2–6%"
        ),
        "valueFormatter": {"function": "params.value != null ? params.value.toFixed(2) + '%' : '—'"},
        "cellStyle": {
            "function": (
                "params.data.dy_pass "
                "? {color: '#2ecc71', fontWeight: 600} "
                ": {color: '#e67e22', fontWeight: 600}"
            )
        },
    },
]

_ETF_COL_QUARTERLY = _ETF_COL_BASE + [
    {
        "field": "three_month_return",
        "headerName": "3M Return %",
        "width": 115,
        "type": "numericColumn",
        "headerTooltip": (
            "3-Month Total Return %\n\n"
            "Price appreciation + distributions over the past 3 months.\n\n"
            "Context:\n"
            "- > +5%  →  strong short-term momentum\n"
            "- 0–5%   →  modest gain\n"
            "- < 0%   →  recent drawdown"
        ),
        "valueFormatter": {
            "function": (
                "params.value != null "
                "? (params.value >= 0 ? '+' : '') + params.value.toFixed(1) + '%' "
                ": '—'"
            )
        },
        "cellStyle": {
            "function": (
                "params.data.r3m_pass "
                "? {color: '#2ecc71', fontWeight: 600} "
                ": {color: '#e67e22', fontWeight: 600}"
            )
        },
    },
    {
        "field": "six_month_return",
        "headerName": "6M Return %",
        "width": 115,
        "type": "numericColumn",
        "headerTooltip": (
            "6-Month Total Return %\n\n"
            "Price appreciation + distributions over the past 6 months.\n\n"
            "Context:\n"
            "- > +10%  →  strong intermediate momentum\n"
            "- 0–10%   →  modest gain\n"
            "- < 0%    →  underperformance over the half-year"
        ),
        "valueFormatter": {
            "function": (
                "params.value != null "
                "? (params.value >= 0 ? '+' : '') + params.value.toFixed(1) + '%' "
                ": '—'"
            )
        },
        "cellStyle": {
            "function": (
                "params.data.r6m_pass "
                "? {color: '#2ecc71', fontWeight: 600} "
                ": {color: '#e67e22', fontWeight: 600}"
            )
        },
    },
]

_ETF_COL_ANNUAL = _ETF_COL_BASE + [
    {
        "field": "one_yr_return",
        "headerName": "1Y Return %",
        "width": 115,
        "type": "numericColumn",
        "headerTooltip": (
            "1-Year Total Return %\n\n"
            "Price appreciation + distributions over the past 12 months.\n\n"
            "Long-run S&P 500 average is ~10%/year.\n\n"
            "Context:\n"
            "- > +15%  →  outperforming broad market\n"
            "- 5–15%   →  in line with equities\n"
            "- < 0%    →  annual drawdown"
        ),
        "valueFormatter": {
            "function": (
                "params.value != null "
                "? (params.value >= 0 ? '+' : '') + params.value.toFixed(1) + '%' "
                ": '—'"
            )
        },
        "cellStyle": {
            "function": (
                "params.data.r1_pass "
                "? {color: '#2ecc71', fontWeight: 600} "
                ": {color: '#e67e22', fontWeight: 600}"
            )
        },
    },
    {
        "field": "three_yr_return",
        "headerName": "3Y Avg Return %",
        "width": 135,
        "type": "numericColumn",
        "headerTooltip": (
            "3-Year Annualised Total Return %\n\n"
            "Compound annual growth rate (CAGR) over 3 years including distributions.\n"
            "Smooths out short-term noise — a more reliable quality signal.\n\n"
            "Long-run S&P 500 average is ~10%/year.\n\n"
            "Context:\n"
            "- > +12%  →  consistently strong\n"
            "- 5–12%   →  solid long-term performance\n"
            "- < 0%    →  destruction of capital over the period"
        ),
        "valueFormatter": {
            "function": (
                "params.value != null "
                "? (params.value >= 0 ? '+' : '') + params.value.toFixed(1) + '%' "
                ": '—'"
            )
        },
        "cellStyle": {
            "function": (
                "params.data.r3_pass "
                "? {color: '#2ecc71', fontWeight: 600} "
                ": {color: '#e67e22', fontWeight: 600}"
            )
        },
    },
]

# ---------------------------------------------------------------------------
# Stock screener column definitions (mirrors screener.py _COLUMNS)
# ---------------------------------------------------------------------------

_STOCK_COLUMNS = [
    {"field": "ticker",   "headerName": "Ticker",  "width": 90,  "pinned": "left",
     "tooltipField": "description",
     "headerTooltip": "Hover over a ticker to read the company's business description."},
    {"field": "name",     "headerName": "Company", "minWidth": 150, "flex": 2,
     "wrapText": True, "autoHeight": True},
    {"field": "sector",   "headerName": "Sector",  "minWidth": 110, "flex": 1,
     "wrapText": True, "autoHeight": True},
    {
        "field": "period_end",
        "headerName": "Period",
        "width": 82,
        "valueFormatter": {"function": "params.value ? params.value.slice(2) : '—'"},
    },
    {
        "field": "quality_score",
        "headerName": "Score",
        "width": 80,
        "type": "numericColumn",
        "headerTooltip": (
            "Quality Score (0–100)\n\n"
            "Each of the five core metrics earns up to 20 pts:\n"
            "  Gross Margin ≥ 40%  → 20 pts  (neutral ≥ 15%  → 10 pts)\n"
            "  ROIC ≥ 12%          → 20 pts  (neutral ≥ 5%   → 10 pts)\n"
            "  FCF Margin ≥ 10%    → 20 pts  (neutral > 0%   → 10 pts)\n"
            "  Int. Coverage ≥ 3×  → 20 pts  (neutral > 1×   → 10 pts)\n"
            "  P/E ≤ 15            → 20 pts  (neutral < 40   → 10 pts)\n\n"
            "80–100: high quality  |  50–79: acceptable  |  < 50: weak"
        ),
        "valueFormatter": {"function": "params.value != null ? params.value.toFixed(0) : '—'"},
        "cellStyle": {
            "function": (
                "params.value != null ? ("
                "  params.value >= 80 ? {color: '#2ecc71', fontWeight: 600} :"
                "  params.value >= 50 ? {color: '#f39c12', fontWeight: 600} :"
                "  {color: '#e67e22', fontWeight: 600}"
                ") : {}"
            )
        },
    },
    {
        "field": "gross_margin",
        "headerName": "Gross Margin %",
        "width": 130,
        "type": "numericColumn",
        "valueFormatter": {"function": "params.value != null ? params.value.toFixed(1) + '%' : '—'"},
        "cellStyle": {
            "function": (
                "params.data.gm_pass ? {color: '#2ecc71', fontWeight: 600} : "
                "{color: '#e67e22', fontWeight: 600}"
            )
        },
    },
    {
        "field": "roic",
        "headerName": "ROIC",
        "width": 90,
        "type": "numericColumn",
        "valueFormatter": {"function": "params.value != null ? (params.value * 100).toFixed(1) + '%' : '—'"},
        "cellStyle": {
            "function": "params.data.roic_pass ? {color: '#2ecc71', fontWeight: 600} : {color: '#e67e22', fontWeight: 600}"
        },
    },
    {
        "field": "fcf_margin",
        "headerName": "FCF Margin %",
        "width": 120,
        "type": "numericColumn",
        "valueFormatter": {"function": "params.value != null ? params.value.toFixed(1) + '%' : '—'"},
        "cellStyle": {
            "function": "params.data.fcf_pass ? {color: '#2ecc71', fontWeight: 600} : {color: '#e67e22', fontWeight: 600}"
        },
    },
    {
        "field": "interest_coverage",
        "headerName": "Int. Coverage",
        "width": 120,
        "type": "numericColumn",
        "valueFormatter": {"function": "params.value != null ? params.value.toFixed(2) + 'x' : '—'"},
        "cellStyle": {
            "function": "params.data.ic_pass ? {color: '#2ecc71', fontWeight: 600} : {color: '#e67e22', fontWeight: 600}"
        },
    },
    {
        "field": "pe_ratio",
        "headerName": "P/E",
        "width": 80,
        "type": "numericColumn",
        "valueFormatter": {"function": "params.value != null ? params.value.toFixed(1) : '—'"},
        "cellStyle": {
            "function": "params.data.pe_pass ? {color: '#2ecc71', fontWeight: 600} : {color: '#e67e22', fontWeight: 600}"
        },
    },
    {
        "field": "pb_ratio",
        "headerName": "P/B",
        "width": 80,
        "type": "numericColumn",
        "valueFormatter": {"function": "params.value != null ? params.value.toFixed(2) : '—'"},
    },
    {
        "field": "pe_x_pb",
        "headerName": "P/E×P/B",
        "width": 95,
        "type": "numericColumn",
        "headerTooltip": "Graham's combined criterion: P/E × P/B ≤ 22.5 → green.",
        "valueFormatter": {"function": "params.value != null ? params.value.toFixed(1) : '—'"},
        "cellStyle": {
            "function": (
                "params.value != null ? ("
                "  params.value <= 22.5 ? {color: '#2ecc71', fontWeight: 600} : {}"
                ") : {}"
            )
        },
    },
    {
        "field": "graham_number",
        "headerName": "Graham #",
        "width": 100,
        "type": "numericColumn",
        "valueFormatter": {"function": "params.value != null ? '$' + params.value.toFixed(2) : '—'"},
        "cellStyle": {
            "function": (
                "params.data.current_price != null && params.value != null ? ("
                "  params.data.current_price <= params.value ? {color: '#2ecc71', fontWeight: 600} : {}"
                ") : {}"
            )
        },
    },
    {
        "field": "ncav_per_share",
        "headerName": "NCAV/Shr",
        "width": 100,
        "type": "numericColumn",
        "valueFormatter": {"function": "params.value != null ? '$' + params.value.toFixed(2) : '—'"},
    },
    {
        "field": "current_ratio",
        "headerName": "Curr. Ratio",
        "width": 105,
        "type": "numericColumn",
        "valueFormatter": {"function": "params.value != null ? params.value.toFixed(2) : '—'"},
        "cellStyle": {
            "function": (
                "params.value != null ? ("
                "  params.value >= 2.0 ? {color: '#2ecc71', fontWeight: 600} :"
                "  params.value >= 1.0 ? {} :"
                "  {color: '#e67e22', fontWeight: 600}"
                ") : {}"
            )
        },
    },
    {
        "field": "roe",
        "headerName": "ROE",
        "width": 80,
        "type": "numericColumn",
        "valueFormatter": {"function": "params.value != null ? (params.value * 100).toFixed(1) + '%' : '—'"},
    },
    {
        "field": "current_price",
        "headerName": "Price",
        "width": 90,
        "type": "numericColumn",
        "valueFormatter": {"function": "params.value != null ? '$' + params.value.toFixed(2) : '—'"},
    },
]

_DEFAULT_COL = {
    "sortable": True,
    "filter": True,
    "resizable": True,
    "wrapText": True,
    "autoHeight": True,
    "cellStyle": {
        "backgroundColor": "transparent",
        "color": "#ffffff",
        "whiteSpace": "normal",
        "lineHeight": "1.4",
    },
}


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------

def _thresh(label: str, comp_id: str, placeholder: str, step: float = 0.1) -> html.Div:
    return html.Div([
        html.Div(label, style={"fontSize": "0.70rem", "color": "#888888", "marginBottom": "3px"}),
        dbc.Input(
            id=comp_id,
            type="number",
            placeholder=placeholder,
            step=step,
            debounce=True,
            size="sm",
            style={"backgroundColor": "#0d0d0d", "color": "#ffffff",
                   "border": "1px solid #2a2a2a", "padding": "4px 8px"},
        ),
    ])


def _section(text: str) -> html.Div:
    return html.Div(text, style={
        "fontSize": "0.68rem", "fontWeight": 700, "letterSpacing": "0.08em",
        "color": "#666666", "textTransform": "uppercase", "marginBottom": "6px",
    })


_PERIOD_RADIO = dbc.RadioItems(
    id="etf-period",
    options=[
        {"label": "Quarterly", "value": "quarterly"},
        {"label": "Annual",    "value": "annual"},
    ],
    value="quarterly",
    inline=True,
    style={"fontSize": "0.82rem", "color": "#aaaaaa"},
    inputStyle={"marginRight": "4px"},
    labelStyle={"marginRight": "14px"},
)


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

layout = html.Div([
    # Title
    html.Div([
        html.Span("ETF ", className="page-title"),
        html.Span("Screener", className="page-title title-accent"),
    ], style={"marginBottom": "14px"}),

    # Stores
    dcc.Store(id="etf-active-group", data="all"),
    dcc.Store(id="etf-groups-store", data={}),
    # One-shot interval to load groups from API on page load
    dcc.Interval(id="etf-init-interval", interval=500, max_intervals=1, n_intervals=0),

    # -----------------------------------------------------------------------
    # Top control bar: Group dropdown + Period selector
    # -----------------------------------------------------------------------
    dbc.Row([
        dbc.Col([
            html.Div("View", style={"fontSize": "0.70rem", "color": "#888888", "marginBottom": "3px"}),
            dcc.Dropdown(
                id="etf-group-dropdown",
                options=_DEFAULT_DROPDOWN_OPTIONS,
                value="all",
                clearable=False,
                searchable=False,
                style={
                    "backgroundColor": "#111111",
                    "color": "#ffffff",
                    "border": "1px solid #2a2a2a",
                    "borderRadius": "4px",
                    "fontSize": "0.85rem",
                    "minWidth": "220px",
                },
                className="etf-dropdown",
            ),
        ], md=4),

        dbc.Col([
            html.Div("Period", style={"fontSize": "0.70rem", "color": "#888888", "marginBottom": "6px"}),
            _PERIOD_RADIO,
        ], md=4, style={"display": "flex", "flexDirection": "column", "justifyContent": "flex-start"}),

        dbc.Col(
            html.Div(id="etf-mode-banner", style={"display": "none"}),
            md=4,
        ),
    ], className="mb-3 align-items-end"),

    # -----------------------------------------------------------------------
    # Collapsible filter panel
    # -----------------------------------------------------------------------
    html.Div([
        dbc.Button(
            [
                html.Span(id="etf-filter-arrow", children="▼",
                          style={"marginRight": "6px", "fontSize": "0.75rem"}),
                "Screen Filters",
            ],
            id="etf-filter-toggle",
            color="link",
            size="sm",
            style={
                "color": "#aaaaaa", "textDecoration": "none", "fontWeight": 600,
                "fontSize": "0.82rem", "padding": "8px 14px", "letterSpacing": "0.04em",
                "width": "100%", "textAlign": "left",
                "backgroundColor": "#111111", "border": "1px solid #2a2a2a",
                "borderRadius": "4px 4px 0 0",
            },
        ),
        dbc.Collapse(
            html.Div([
                dbc.Row([
                    # Quick presets (always shown)
                    dbc.Col([
                        _section("Quick Presets"),
                        html.Div([
                            dbc.Button("High Quality", id="etf-preset-quality", size="sm",
                                       color="success", outline=True, className="preset-btn",
                                       style={"marginRight": "4px", "marginBottom": "4px"}),
                            dbc.Button("Value",        id="etf-preset-value",   size="sm",
                                       color="info",    outline=True, className="preset-btn",
                                       style={"marginRight": "4px", "marginBottom": "4px"}),
                            dbc.Button("Growth",       id="etf-preset-growth",  size="sm",
                                       color="warning", outline=True, className="preset-btn",
                                       style={"marginRight": "4px", "marginBottom": "4px"}),
                            dbc.Button("Clear",        id="etf-preset-clear",   size="sm",
                                       color="secondary", className="preset-btn",
                                       style={"marginBottom": "4px"}),
                        ]),
                    ], md=3, style={"borderRight": "1px solid #222", "paddingRight": "14px"}),

                    # ETF-specific filters (hidden in stock mode)
                    html.Div(
                        id="etf-etf-filters",
                        children=dbc.Col([
                            _section("ETF Filters"),
                            dbc.Row([
                                dbc.Col(_thresh("Max Expense Ratio %", "etf-th-expense", "e.g. 0.20"), md=4),
                                dbc.Col(_thresh("Min Div. Yield %",    "etf-th-yield",   "e.g. 2.0", 0.1), md=4),
                                dbc.Col(_thresh("Min AUM ($B)",        "etf-th-aum",     "e.g. 10",  1.0), md=4),
                            ], className="g-2 mb-2"),
                            dbc.Row([
                                dbc.Col(_thresh("Min 1Y Return %",     "etf-th-1yr",     "e.g. 10",  1.0), md=4),
                                dbc.Col(_thresh("Min 3Y Avg Return %", "etf-th-3yr",     "e.g. 5",   1.0), md=4),
                                dbc.Col(_thresh("Max P/E",             "etf-th-pe",      "e.g. 25",  1.0), md=4),
                            ], className="g-2"),
                        ], md=12),
                    ),

                    # Stock-specific filters (hidden in ETF mode)
                    html.Div(
                        id="etf-stock-filters",
                        style={"display": "none"},
                        children=dbc.Col([
                            _section("Stock Filters"),
                            dbc.Row([
                                dbc.Col(_thresh("Min GM %",           "etf-th-gm",  "e.g. 40"), md=4),
                                dbc.Col(_thresh("Min ROIC",           "etf-th-roic","e.g. 0.10", 0.01), md=4),
                                dbc.Col(_thresh("Min FCF %",          "etf-th-fcf", "e.g. 5"),   md=4),
                            ], className="g-2 mb-2"),
                            dbc.Row([
                                dbc.Col(_thresh("Min Int. Cov. (x)",  "etf-th-ic",     "e.g. 3"),        md=3),
                                dbc.Col(_thresh("Max P/E",            "etf-th-pe-stock","e.g. 35"),       md=3),
                                dbc.Col(_thresh("Min Score (0–100)",  "etf-th-score",   "e.g. 60", 1.0),  md=3),
                                dbc.Col(
                                    dbc.Checklist(
                                        options=[{"label": " Hide N/A", "value": "hide_na"}],
                                        value=[],
                                        id="etf-hide-na",
                                        switch=True,
                                        style={"color": "#aaaaaa", "fontSize": "0.82rem",
                                               "marginTop": "20px"},
                                    ), md=3
                                ),
                            ], className="g-2"),
                        ], md=12),
                    ),

                    # Data management (always shown)
                    dbc.Col([
                        _section("Data"),
                        dbc.Button(
                            [html.I(className="bi-arrow-clockwise me-2"), "Refresh ETF Data"],
                            id="etf-refresh-btn",
                            color="secondary", size="sm", outline=True,
                            style={"width": "100%", "marginBottom": "6px"},
                        ),
                        dbc.Button(
                            [html.I(className="bi-download me-2"), "Fetch Missing Stocks"],
                            id="etf-fetch-missing-btn",
                            color="primary", size="sm", outline=True,
                            style={"width": "100%", "display": "none", "marginBottom": "6px"},
                        ),
                        dbc.InputGroup([
                            dbc.Input(
                                id="etf-add-ticker-input",
                                placeholder="Add ticker (e.g. 005930.KS)",
                                size="sm",
                                style={"backgroundColor": "#0d0d0d", "color": "#ffffff",
                                       "border": "1px solid #2a2a2a"},
                            ),
                            dbc.Button("Add", id="etf-add-ticker-btn",
                                       color="success", size="sm", outline=True),
                        ], style={"marginBottom": "6px"}),
                        dbc.InputGroup([
                            dbc.Input(
                                id="etf-remove-ticker-input",
                                placeholder="TICKER to remove",
                                size="sm",
                                style={"backgroundColor": "#0d0d0d", "color": "#ffffff",
                                       "border": "1px solid #2a2a2a"},
                            ),
                            dbc.Button("Remove", id="etf-remove-ticker-btn",
                                       color="danger", size="sm", outline=True),
                        ], style={"marginBottom": "6px"}),
                        dcc.Loading(
                            html.Div(id="etf-refresh-status",
                                     style={"marginTop": "6px", "fontSize": "0.78rem",
                                            "color": "#2ecc71"}),
                        ),
                    ], md=3, style={"borderLeft": "1px solid #222", "paddingLeft": "14px"}),

                ], className="g-3"),

                dbc.Row([
                    dbc.Col(
                        dbc.Checklist(
                            options=[{"label": " Hide N/A rows", "value": "hide_na"}],
                            value=[],
                            id="etf-hide-na-etf",
                            switch=True,
                            style={"color": "#aaaaaa", "fontSize": "0.82rem"},
                        ), md=3, style={"marginTop": "10px"},
                    ),
                ]),
            ], style={"backgroundColor": "#111111", "padding": "14px 16px",
                      "border": "1px solid #2a2a2a", "borderTop": "none",
                      "borderRadius": "0 0 4px 4px"}),
            id="etf-filter-collapse",
            is_open=True,
        ),
    ], style={"marginBottom": "14px"}),

    # -----------------------------------------------------------------------
    # Results
    # -----------------------------------------------------------------------
    dbc.Row([
        dbc.Col(
            dbc.InputGroup([
                dbc.InputGroupText(
                    html.I(className="bi-search"),
                    style={"backgroundColor": "#1a1a1a", "border": "1px solid #2a2a2a",
                           "color": "#888888"},
                ),
                dbc.Input(
                    id="etf-search",
                    placeholder="Search ticker or name…",
                    debounce=False,
                    size="sm",
                    style={"backgroundColor": "#111111", "color": "#ffffff",
                           "border": "1px solid #2a2a2a", "borderLeft": "none"},
                ),
            ]),
            md=5,
        ),
        dbc.Col(
            html.Div(id="etf-meta",
                     style={"color": "#aaaaaa", "fontSize": "0.80rem",
                            "paddingTop": "6px"}),
            md=5,
        ),
        dbc.Col(
            html.Small(
                "Cached 5 min.",
                id="etf-cache-note",
                style={"color": "#555555", "fontSize": "0.70rem",
                       "paddingTop": "8px", "display": "block",
                       "textAlign": "right"},
            ),
            md=2,
        ),
    ], className="mb-2"),

    dcc.Loading(
        dag.AgGrid(
            id="etf-grid",
            columnDefs=_ETF_COL_ANNUAL,
            defaultColDef=_DEFAULT_COL,
            rowData=[],
            dashGridOptions={
                "pagination": True,
                "paginationPageSize": 50,
                "rowSelection": "single",
                "suppressCellFocus": True,
                "tooltipShowDelay": 400,
                "tooltipHideDelay": 12000,
                "tooltipInteraction": True,
            },
            style={"height": "75vh"},
            className="ag-theme-alpine-dark",
        ),
    ),
])


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

# Load groups from API on page load and after explicit refresh
@callback(
    Output("etf-groups-store", "data"),
    Input("etf-init-interval", "n_intervals"),
    Input("etf-refresh-btn",   "n_clicks"),
    prevent_initial_call=False,
)
def load_etf_groups(_interval, _refresh):
    groups = get_etf_groups()
    return groups or {}


# Populate dropdown options from groups store
@callback(
    Output("etf-group-dropdown", "options"),
    Input("etf-groups-store", "data"),
)
def populate_group_dropdown(groups: dict):
    if not groups:
        return _DEFAULT_DROPDOWN_OPTIONS
    return _build_dropdown_options(groups)


# Dropdown selection → active group store
@callback(
    Output("etf-active-group", "data"),
    Input("etf-group-dropdown", "value"),
)
def update_active_group(value):
    return value or "all"


# Active group → show/hide mode-specific UI elements
@callback(
    Output("etf-mode-banner",      "children"),
    Output("etf-mode-banner",      "style"),
    Output("etf-etf-filters",      "style"),
    Output("etf-stock-filters",    "style"),
    Output("etf-fetch-missing-btn","style"),
    Output("etf-cache-note",       "style"),
    Input("etf-active-group", "data"),
    State("etf-groups-store", "data"),
)
def update_mode_ui(group: str, groups: dict):
    group = group or "all"
    groups = groups or {}
    is_custom = _is_custom_group(group, groups)
    is_stock  = group in _STOCK_MODE_GROUPS or is_custom

    group_label = (groups.get(group) or {}).get("label") or _STATIC_LABELS.get(group, group)

    if is_stock:
        if is_custom:
            detail = (
                f"Showing stock fundamentals for the top holdings of {group_label} "
                "fetched from yfinance (typically top 10–25). "
                "Click 'Fetch Missing Stocks' to load any not yet in your local database."
            )
        else:
            detail = (
                f"Showing individual stock fundamentals for {group_label} constituents "
                "(top 100 by market cap). Data sourced from your local database — "
                "click 'Fetch Missing Stocks' to load any stocks not yet cached."
            )
        banner_content = html.Div([
            html.I(className="bi-info-circle me-2", style={"color": "#4a90e2"}),
            html.Span(detail, style={"fontSize": "0.82rem", "color": "#aaaaaa"}),
        ], style={
            "backgroundColor": "#0d1a2d", "border": "1px solid #1a3a5c",
            "borderRadius": "4px", "padding": "10px 14px",
            "display": "flex", "alignItems": "center",
        })
        banner_style       = {}
        etf_filter_style   = {"display": "none"}
        stock_filter_style = {}
        fetch_btn_style    = {"width": "100%", "marginBottom": "6px"}
        cache_note_style   = {"display": "none"}
    else:
        banner_content = []
        banner_style       = {"display": "none"}
        etf_filter_style   = {}
        stock_filter_style = {"display": "none"}
        fetch_btn_style    = {"display": "none"}
        cache_note_style   = {
            "color": "#555555", "fontSize": "0.70rem",
            "paddingTop": "8px", "display": "block", "textAlign": "right",
        }

    return (banner_content, banner_style, etf_filter_style,
            stock_filter_style, fetch_btn_style, cache_note_style)


# Toggle filter panel open/closed
@callback(
    Output("etf-filter-collapse", "is_open"),
    Output("etf-filter-arrow",    "children"),
    Input("etf-filter-toggle",    "n_clicks"),
    State("etf-filter-collapse",  "is_open"),
    prevent_initial_call=True,
)
def toggle_filters(_, is_open: bool):
    new_open = not is_open
    return new_open, "▼" if new_open else "▶"


# Main data callback
@callback(
    Output("etf-grid", "rowData"),
    Output("etf-grid", "columnDefs"),
    Output("etf-meta", "children"),
    Input("etf-active-group",  "data"),
    Input("etf-period",        "value"),
    # ETF mode filters
    Input("etf-th-expense",    "value"),
    Input("etf-th-yield",      "value"),
    Input("etf-th-1yr",        "value"),
    Input("etf-th-3yr",        "value"),
    Input("etf-th-aum",        "value"),
    Input("etf-th-pe",         "value"),
    Input("etf-hide-na-etf",   "value"),
    # Stock mode filters
    Input("etf-th-gm",         "value"),
    Input("etf-th-roic",       "value"),
    Input("etf-th-fcf",        "value"),
    Input("etf-th-ic",         "value"),
    Input("etf-th-pe-stock",   "value"),
    Input("etf-th-score",      "value"),
    Input("etf-hide-na",       "value"),
    # Common
    Input("etf-refresh-btn",   "n_clicks"),
    Input("etf-search",        "value"),
    State("etf-groups-store",  "data"),
)
def update_etf_grid(
    group, period,
    expense, yield_, r1, r3, aum, pe_etf, hide_na_etf_val,
    gm, roic, fcf, ic, pe_stock, score, hide_na_stock_val,
    _refresh, search, groups_store,
):
    group  = group  or "all"
    period = period or "annual"
    is_custom = _is_custom_group(group, groups_store)
    is_stock  = group in _STOCK_MODE_GROUPS or is_custom

    if is_stock:
        hide_na = "hide_na" in (hide_na_stock_val or [])
        result = get_index_stocks(
            group=group,
            max_n=100,
            period_type=period,
            min_gross_margin=gm,
            min_roic=roic,
            min_fcf_margin=fcf,
            min_interest_coverage=ic,
            max_pe=pe_stock,
            min_score=score,
            hide_na=hide_na,
        )
        if not result:
            return [], _STOCK_COLUMNS, "API unavailable."

        rows   = [dict(r) for r in result.get("rows", [])]
        loaded = result.get("loaded", 0)
        total  = result.get("total_constituents", 0)

        # Label: prefer the group's human name from the store, then static table, then raw key
        group_label = (
            (groups_store or {}).get(group, {}).get("label")
            or _STATIC_LABELS.get(group, group)
        )

        if search and search.strip():
            s = search.strip().lower()
            rows = [
                r for r in rows
                if s in (r.get("ticker") or "").lower()
                or s in (r.get("name") or "").lower()
            ]

        # Custom ETF with zero constituents means holdings fetch failed on the server
        if is_custom and total == 0:
            meta = (
                f"⚠ Could not fetch holdings for {group_label}. "
                "No constituent data is available for this ETF. "
                "For Korean ETFs not in the built-in list, holdings data requires "
                "a compatible pykrx installation."
            )
            return [], _STOCK_COLUMNS, meta

        period_label = "Quarterly" if period == "quarterly" else "Annual"
        cap_note     = "top holdings" if is_custom else "top 100 by market cap"
        shown = len(rows)
        meta = (
            f"Showing {shown} of {loaded} loaded stocks  ·  "
            f"{group_label} ({cap_note})  ·  {period_label}"
        )
        if total > loaded:
            meta += f"  ·  {total - loaded} not yet in DB"
        return rows, _STOCK_COLUMNS, meta

    else:
        hide_na = "hide_na" in (hide_na_etf_val or [])
        result = get_etf_screener(
            group=group if group != "all" else None,
            max_expense_ratio=expense,
            min_dividend_yield=yield_,
            min_one_yr_return=r1,
            min_three_yr_return=r3,
            min_aum_b=aum,
            max_pe=pe_etf,
            hide_na=hide_na,
        )
        if not result:
            return [], _ETF_COL_ANNUAL, "API unavailable."

        rows  = result.get("rows", [])
        total = result.get("total", len(rows))

        if search and search.strip():
            s = search.strip().lower()
            rows = [
                r for r in rows
                if s in (r.get("ticker") or "").lower()
                or s in (r.get("name") or "").lower()
            ]

        col_defs = _ETF_COL_QUARTERLY if period == "quarterly" else _ETF_COL_ANNUAL
        period_label = "3M / 6M returns" if period == "quarterly" else "1Y / 3Y returns"

        group_label = _STATIC_LABELS.get(group, group) if group != "all" else "All ETFs"
        shown = len(rows)
        meta = f"Showing {shown} of {total} ETFs  ·  {group_label}  ·  {period_label}"
        if search and search.strip() and shown != total:
            meta += f"  ·  filtered by \"{search.strip()}\""
        return rows, col_defs, meta


# Preset buttons → threshold inputs (ETF filters)
@callback(
    Output("etf-th-expense",  "value"),
    Output("etf-th-yield",    "value"),
    Output("etf-th-1yr",      "value"),
    Output("etf-th-3yr",      "value"),
    Output("etf-th-aum",      "value"),
    Output("etf-th-pe",       "value"),
    Input("etf-preset-quality", "n_clicks"),
    Input("etf-preset-value",   "n_clicks"),
    Input("etf-preset-growth",  "n_clicks"),
    Input("etf-preset-clear",   "n_clicks"),
    prevent_initial_call=True,
)
def apply_etf_preset(q, v, g, c):
    trigger = dash.ctx.triggered_id
    presets = {
        "etf-preset-quality": (0.20,  None,  None,  5.0,  10.0, None),
        "etf-preset-value":   (None,  2.0,   None,  None, None, 20.0),
        "etf-preset-growth":  (None,  None,  10.0,  None, None, None),
        "etf-preset-clear":   (None,  None,  None,  None, None, None),
    }
    return presets.get(trigger, (None, None, None, None, None, None))


# Refresh button: bust server-side ETF cache
@callback(
    Output("etf-refresh-status", "children"),
    Input("etf-refresh-btn", "n_clicks"),
    prevent_initial_call=True,
)
def refresh_etf_data(_):
    from frontend.api_client import admin_refresh_etf
    res = admin_refresh_etf()
    if res:
        return "Cache cleared — live data will load on next fetch."
    return "Refresh failed — check API connection."


# Add ticker button — updates both the status message and the groups store atomically
# so the dropdown reflects the new ticker without a separate refresh step.
@callback(
    Output("etf-refresh-status", "children", allow_duplicate=True),
    Output("etf-groups-store",   "data",     allow_duplicate=True),
    Input("etf-add-ticker-btn",  "n_clicks"),
    State("etf-add-ticker-input", "value"),
    prevent_initial_call=True,
)
def add_etf_ticker_cb(n_clicks, add_input):
    no_update = dash.no_update
    if not n_clicks or not add_input or not add_input.strip():
        return "", no_update
    sym = add_input.strip().upper()
    res = admin_add_etf_ticker(sym)
    if res is None:
        return "Add failed — could not reach API. Is the server running?", no_update
    if "error" in res:
        return html.Span(res["error"], style={"color": "#e74c3c"}), no_update
    # Fetch the updated groups list now that the ticker is registered on the server
    updated_groups = get_etf_groups() or {}
    if res.get("added"):
        return f"Added {sym} to ETF list.", updated_groups
    return f"{sym} is already in the ETF list.", updated_groups


# Remove ticker button
@callback(
    Output("etf-refresh-status", "children", allow_duplicate=True),
    Input("etf-remove-ticker-btn", "n_clicks"),
    State("etf-remove-ticker-input", "value"),
    prevent_initial_call=True,
)
def remove_etf_ticker_cb(n_clicks, remove_input):
    if not n_clicks or not remove_input or not remove_input.strip():
        return ""
    sym = remove_input.strip().upper()
    res = admin_remove_etf_ticker(sym)
    if res is None:
        return f"Remove failed — could not reach API for {sym}."
    if res.get("removed"):
        return f"Removed {sym} from ETF list. Refresh to update the view."
    return f"{sym} was not found in the ETF list."


# Fetch missing stocks button (stock mode only)
@callback(
    Output("etf-refresh-status", "children", allow_duplicate=True),
    Input("etf-fetch-missing-btn", "n_clicks"),
    State("etf-active-group",  "data"),
    State("etf-groups-store",  "data"),
    prevent_initial_call=True,
)
def fetch_missing_stocks(n_clicks, group, groups_store):
    is_stock_group = group in _STOCK_MODE_GROUPS or _is_custom_group(group, groups_store)
    if not n_clicks or not is_stock_group:
        return ""
    result = get_index_stocks(group=group, max_n=100)
    if not result:
        return "API unavailable."
    total   = result.get("total_constituents", 0)
    missing = result.get("missing_tickers", [])
    if total == 0 and _is_custom_group(group, groups_store):
        return (
            "Holdings unavailable: no constituent data found for this ETF. "
            "For Korean ETFs not in the built-in list (e.g. TIGER 200 / KODEX 200), "
            "holdings are looked up from a built-in KOSPI 200 list automatically."
        )
    if not missing:
        return "All constituent stocks are already loaded."
    batch = missing[:20]
    res = admin_fetch(batch)
    if res:
        admin_compute()
        admin_classify()
        names = ", ".join(batch[:5])
        suffix = "..." if len(batch) > 5 else ""
        return f"Fetched {len(batch)} stocks ({names}{suffix}). Reload the page to see results."
    return "Fetch failed — check API connection."
