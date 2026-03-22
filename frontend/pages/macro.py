"""
frontend.pages.macro
====================
Page 7 – Macro / Liquidity Monitor (expanded).

Tabs
----
Liquidity  — Fed Balance Sheet, Net Liquidity (WALCL - RRP - TGA), M1/M2
Inflation  — CPI, Core PCE, PCE, 10Y Breakeven, WTI Oil
Labor      — Unemployment Rate, Initial Jobless Claims
Credit     — 10Y-2Y Spread, 10-Year Rate, HY Credit Spread, VIX, USD Index

Top of page shows:
- Net Liquidity KPI card with QE/QT regime badge
- Latest Values row for all series
"""

from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from dash import Input, Output, callback, dcc, html

from frontend.api_client import get_liquidity, get_macro_latest, get_macro_series

dash.register_page(__name__, path="/macro", name="Macro Monitor", title="Macro Monitor")

# ---------------------------------------------------------------------------
# Series metadata (label, colour, unit, description, tab group)
# ---------------------------------------------------------------------------

_SERIES: dict[str, dict] = {
    # --- Liquidity tab ---
    "WALCL": {
        "label":  "Fed Total Assets",
        "colour": "#4a90e2",
        "unit":   "Billions USD",
        "tab":    "liquidity",
        "desc": (
            "Federal Reserve's total balance sheet assets — the primary 'money printing' signal. "
            "Rises when the Fed buys Treasuries or MBS (QE). Falls during Quantitative Tightening (QT). "
            "Weekly H.4.1 release."
        ),
    },
    "M2SL": {
        "label":  "M2 Money Supply",
        "colour": "#5ba3e8",
        "unit":   "Billions USD",
        "tab":    "liquidity",
        "desc": (
            "Broad US money supply: cash + checking + savings + money market funds. "
            "Rapid M2 growth tends to be inflationary; contraction signals tighter liquidity. Monthly."
        ),
    },
    "M1SL": {
        "label":  "M1 Money Supply",
        "colour": "#3a78c9",
        "unit":   "Billions USD",
        "tab":    "liquidity",
        "desc": (
            "Narrow money supply: physical currency + demand deposits. "
            "A more immediate measure of transactional money in the economy. Monthly."
        ),
    },
    "RRPONTSYD": {
        "label":  "Overnight Reverse Repo",
        "colour": "#e94560",
        "unit":   "Billions USD",
        "tab":    "liquidity",
        "desc": (
            "ON RRP balance at the NY Fed — money market funds park excess cash here. "
            "High RRP = liquidity trapped at the Fed, not in markets. "
            "Declining RRP often coincides with rising risk appetite. Daily."
        ),
    },
    "WDTGAL": {
        "label":  "Treasury General Account (TGA)",
        "colour": "#c0392b",
        "unit":   "Billions USD",
        "tab":    "liquidity",
        "desc": (
            "Treasury's checking account at the Fed. When the TGA falls (Treasury spending), "
            "cash flows into the banking system — bullish for liquidity. "
            "Rising TGA drains liquidity. Weekly."
        ),
    },
    "FEDFUNDS": {
        "label":  "Fed Funds Rate",
        "colour": "#f0c040",
        "unit":   "%",
        "tab":    "liquidity",
        "desc": (
            "Federal Reserve target overnight lending rate. The most important lever of US monetary policy. "
            "Higher rates raise borrowing costs; lower rates stimulate. Monthly average."
        ),
    },
    # --- Inflation tab ---
    "CPIAUCSL": {
        "label":  "CPI (All Urban)",
        "colour": "#e67e22",
        "unit":   "Index",
        "tab":    "inflation",
        "desc": (
            "Consumer Price Index for All Urban Consumers — primary US inflation gauge. "
            "Fed targets ~2% annual growth. Base period 1982–84 = 100. Monthly, seasonally adjusted."
        ),
    },
    "PCEPI": {
        "label":  "PCE Price Index",
        "colour": "#d35400",
        "unit":   "Index",
        "tab":    "inflation",
        "desc": (
            "Personal Consumption Expenditures Price Index — the Fed's preferred inflation measure. "
            "Tends to run lower than CPI due to different basket weights. Monthly."
        ),
    },
    "PCEPILFE": {
        "label":  "Core PCE (ex Food & Energy)",
        "colour": "#e8a030",
        "unit":   "Index",
        "tab":    "inflation",
        "desc": (
            "Core PCE excluding food and energy — the FOMC's primary inflation gauge for policy decisions. "
            "This is the series cited in Fed press conferences. Monthly."
        ),
    },
    "T10YIE": {
        "label":  "10Y Breakeven Inflation",
        "colour": "#f39c12",
        "unit":   "%",
        "tab":    "inflation",
        "desc": (
            "Market-implied 10-year inflation expectation = 10Y nominal Treasury yield minus 10Y TIPS yield. "
            "Tracks what bond markets expect inflation to average over 10 years. Daily."
        ),
    },
    "DCOILWTICO": {
        "label":  "WTI Crude Oil",
        "colour": "#1abc9c",
        "unit":   "USD/barrel",
        "tab":    "inflation",
        "desc": (
            "West Texas Intermediate crude oil spot price — key input cost across the economy. "
            "High oil directly contributes to headline CPI. Daily price."
        ),
    },
    # --- Labor tab ---
    "UNRATE": {
        "label":  "Unemployment Rate",
        "colour": "#2ecc71",
        "unit":   "%",
        "tab":    "labor",
        "desc": (
            "US civilian unemployment rate — lagging economic indicator. "
            "The Fed's dual mandate: maximum employment + price stability. Monthly."
        ),
    },
    "ICSA": {
        "label":  "Initial Jobless Claims",
        "colour": "#27ae60",
        "unit":   "Thousands",
        "tab":    "labor",
        "desc": (
            "New unemployment insurance filings — a leading indicator of labor market health. "
            "Rising claims signal deteriorating employment conditions. Weekly Thursday release."
        ),
    },
    # --- Credit / Rates / Risk tab ---
    "T10Y2Y": {
        "label":  "10Y-2Y Treasury Spread",
        "colour": "#9b59b6",
        "unit":   "%",
        "tab":    "credit",
        "desc": (
            "Yield curve spread: 10-year minus 2-year Treasury. "
            "Inverted (negative) = historically reliable recession predictor with ~12–18 month lag. Daily."
        ),
    },
    "DGS10": {
        "label":  "10-Year Treasury Rate",
        "colour": "#8e44ad",
        "unit":   "%",
        "tab":    "credit",
        "desc": (
            "10-year US Treasury yield — the global benchmark risk-free rate. "
            "Drives mortgage rates, corporate spreads, and equity discount rates. Daily."
        ),
    },
    "BAMLH0A0HYM2": {
        "label":  "HY Credit Spread",
        "colour": "#e74c3c",
        "unit":   "% (OAS)",
        "tab":    "credit",
        "desc": (
            "ICE BofA High Yield Option-Adjusted Spread — extra yield demanded over Treasuries for junk bonds. "
            "Spikes during credit stress / recession fears. Tight spread = risk appetite. Daily."
        ),
    },
    "VIXCLS": {
        "label":  "VIX Volatility Index",
        "colour": "#c0392b",
        "unit":   "Index",
        "tab":    "credit",
        "desc": (
            "CBOE Volatility Index — the 'fear gauge', 30-day implied volatility on S&P 500. "
            "VIX > 30 = high fear / market stress. VIX < 15 = complacency. Daily."
        ),
    },
    "DTWEXBGS": {
        "label":  "USD Trade-Weighted Index",
        "colour": "#2980b9",
        "unit":   "Index",
        "tab":    "credit",
        "desc": (
            "Broad trade-weighted US dollar index vs major trading partners. "
            "Strong USD = headwind for EM assets and US multinational earnings. Daily."
        ),
    },
}

_TABS = {
    "liquidity": "Liquidity",
    "inflation": "Inflation",
    "labor":     "Labor",
    "credit":    "Credit & Risk",
}

_DAYS_MAP = {"1Y": 365, "2Y": 730, "5Y": 1825, "10Y": 3650, "20Y": 7300}

_REGIME_COLOUR = {"QE": "#2ecc71", "QT": "#e94560", "NEUTRAL": "#f0c040"}
_REGIME_LABEL  = {
    "QE":      "QE — Fed Expanding",
    "QT":      "QT — Fed Tightening",
    "NEUTRAL": "Neutral",
}


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

layout = html.Div([
    html.Div([
        html.Span("Macro / Liquidity ", className="page-title"),
        html.Span("Monitor", className="page-title title-accent"),
    ], style={"marginBottom": "20px"}),

    # Store: updated on refresh to trigger chart/latest reloads
    dcc.Store(id="macro-data-store", data={}),

    # Timeframe selector + refresh button
    dbc.Row([
        dbc.Col([
            html.Div("Timeframe", className="threshold-label"),
            dbc.RadioItems(
                id="macro-timeframe",
                options=[{"label": k, "value": k} for k in _DAYS_MAP],
                value="5Y",
                inline=True,
                style={"color": "#ffffff"},
            ),
        ], md=6),
        dbc.Col([
            dbc.Button(
                [html.I(className="bi-arrow-clockwise me-2"), "Refresh Macro Data"],
                id="macro-refresh-btn", color="secondary", size="sm", outline=True,
                style={"float": "right"},
                title="Fetch latest FRED data — requires FRED_API_KEY in .env",
            ),
        ], md=6),
    ], className="mb-3"),

    dcc.Loading(html.Div(id="macro-refresh-status",
                         style={"marginBottom": "10px", "fontSize": "0.82rem",
                                "color": "#2ecc71"})),

    # Net Liquidity KPI + Regime Badge
    html.Div("Fed Net Liquidity", className="section-title"),
    dbc.Row([
        dbc.Col(html.Div(id="macro-net-liquidity-kpi"), md=12),
    ], className="mb-3"),

    # Latest values summary row
    html.Div("Latest Values", className="section-title"),
    dbc.Row(id="macro-latest-row", className="g-3 mb-3"),

    # Tabbed charts
    dbc.Tabs(
        id="macro-tab",
        active_tab="liquidity",
        children=[
            dbc.Tab(label=label, tab_id=tab_id)
            for tab_id, label in _TABS.items()
        ],
        className="mb-3",
        style={"borderBottom": "1px solid #2a2a2a"},
    ),

    dcc.Loading(
        dbc.Row(id="macro-charts-row", className="g-3"),
        type="circle",
        color="#4a90e2",
    ),
])


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

@callback(
    Output("macro-net-liquidity-kpi", "children"),
    Input("macro-data-store", "data"),
    Input("macro-timeframe",  "value"),
)
def update_net_liquidity_kpi(_store, timeframe):
    days = _DAYS_MAP.get(timeframe, 1825)
    liq = get_liquidity(days=days) or {}
    regime = liq.get("regime", "NEUTRAL")
    data   = liq.get("data", [])

    latest_nl   = data[-1]["net_liquidity"] if data else None
    prev_nl     = data[-2]["net_liquidity"] if len(data) >= 2 else None
    delta       = (latest_nl - prev_nl) if latest_nl is not None and prev_nl is not None else None
    delta_str   = f"{'▲' if delta >= 0 else '▼'} {abs(delta):,.1f}B" if delta is not None else "—"
    delta_color = "#2ecc71" if delta is not None and delta >= 0 else "#e94560"

    regime_col = _REGIME_COLOUR.get(regime, "#f0c040")
    regime_lbl = _REGIME_LABEL.get(regime, regime)

    nl_str = f"${latest_nl:,.1f}B" if latest_nl is not None else "No data"

    return dbc.Row([
        dbc.Col(
            html.Div(className="kpi-card", children=[
                html.Div([
                    html.Span("Net Liquidity", className="kpi-label"),
                    html.Span(regime_lbl, style={
                        "marginLeft": "10px",
                        "fontSize": "0.70rem",
                        "fontWeight": "700",
                        "color": regime_col,
                        "border": f"1px solid {regime_col}",
                        "borderRadius": "3px",
                        "padding": "2px 6px",
                        "verticalAlign": "middle",
                    }),
                ], style={"marginBottom": "6px"}),
                html.Div(nl_str, className="kpi-value",
                         style={"fontSize": "1.8rem", "color": "#4a90e2"}),
                html.Div([
                    html.Span("WALCL − RRP − TGA  ",
                              style={"fontSize": "0.70rem", "color": "#888888"}),
                    html.Span(delta_str, style={"fontSize": "0.75rem", "color": delta_color,
                                                "fontWeight": "600"}),
                ]),
            ]),
            md=4,
        ),
        dbc.Col(
            dcc.Loading(_net_liquidity_sparkline(data), type="circle", color="#4a90e2"),
            md=8,
        ),
    ], className="mb-2")


def _net_liquidity_sparkline(data: list[dict]):
    """Build a small Net Liquidity chart overlaid with S&P 500 proxy."""
    fig = go.Figure()
    if data:
        dates = [p["date"] for p in data]
        vals  = [p["net_liquidity"] for p in data]
        fig.add_trace(go.Scatter(
            x=dates, y=vals,
            mode="lines",
            line=dict(color="#4a90e2", width=2),
            fill="tozeroy",
            fillcolor="#4a90e2",
            opacity=0.10,
            name="Net Liquidity",
        ))
    else:
        fig.add_annotation(
            text="Run Refresh to load FRED data",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(color="#888888", size=11),
        )

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#111111",
        plot_bgcolor="#111111",
        font=dict(color="#ffffff", size=10),
        margin=dict(l=50, r=10, t=15, b=30),
        xaxis=dict(gridcolor="#2a2a2a", color="#ffffff", showticklabels=True),
        yaxis=dict(gridcolor="#2a2a2a", title="Billions USD", color="#ffffff"),
        showlegend=False,
        height=140,
    )
    return dcc.Graph(figure=fig, config={"displayModeBar": False})


@callback(
    Output("macro-latest-row", "children"),
    Input("macro-data-store",  "data"),
)
def load_macro_latest(_store):
    data = get_macro_latest() or []
    cards = []
    for item in data:
        sid  = item.get("series_id", "")
        meta = _SERIES.get(sid, {})
        colour = meta.get("colour", "#aaa")
        label  = meta.get("label", sid)
        val    = item.get("value")
        val_str = f"{val:.4g}" if val is not None else "—"
        cards.append(dbc.Col(
            html.Div(className="kpi-card", title=meta.get("desc", ""), children=[
                html.Div(val_str, className="kpi-value",
                         style={"fontSize": "1.4rem", "color": colour}),
                html.Div(label, className="kpi-label",
                         style={"fontSize": "0.68rem"}),
                html.Div(meta.get("unit", ""),
                         style={"fontSize": "0.65rem", "color": "#888888"}),
            ]),
            xs=6, sm=4, md=3, lg=2,
        ))
    if not cards:
        return [dbc.Col(
            html.Div([
                html.I(className="bi-info-circle me-2", style={"color": "#4a90e2"}),
                html.Span("No FRED data yet. Click ",
                          style={"color": "#aaaaaa", "fontSize": "0.85rem"}),
                html.Strong("Refresh Macro Data",
                            style={"color": "#ffffff", "fontSize": "0.85rem"}),
                html.Span(" above to fetch all series (requires FRED_API_KEY in .env).",
                          style={"color": "#aaaaaa", "fontSize": "0.85rem"}),
            ], style={
                "backgroundColor": "#0d1a2d", "border": "1px solid #1a3a5c",
                "borderRadius": "4px", "padding": "12px 16px",
                "display": "flex", "alignItems": "center", "flexWrap": "wrap", "gap": "4px",
            }),
            md=12,
        )]
    return cards


@callback(
    Output("macro-charts-row", "children"),
    Input("macro-tab",         "active_tab"),
    Input("macro-timeframe",   "value"),
    Input("macro-data-store",  "data"),
)
def update_macro_charts(active_tab: str, timeframe: str, _store):
    days = _DAYS_MAP.get(timeframe, 1825)
    tab_series = [sid for sid, m in _SERIES.items() if m.get("tab") == active_tab]

    charts = []
    for sid in tab_series:
        meta   = _SERIES[sid]
        colour = meta["colour"]
        data   = get_macro_series(sid, days=days)

        fig = go.Figure()
        if data and data.get("data"):
            pts   = data["data"]
            dates = [p["date"] for p in pts]
            vals  = [p["value"] for p in pts]
            fig.add_trace(go.Scatter(
                x=dates, y=vals,
                mode="lines",
                line=dict(color=colour, width=2),
                fill="tozeroy",
                fillcolor=colour,
                opacity=0.08,
                name=meta["label"],
            ))
            if sid == "T10Y2Y":
                fig.add_hline(y=0, line_dash="dash", line_color="#ff4444", opacity=0.5)
        else:
            fig.add_annotation(
                text="No data — click Refresh",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False,
                font=dict(color="#888888", size=11),
            )

        # Description card below chart
        desc_div = html.Div(
            meta.get("desc", ""),
            style={
                "fontSize": "0.72rem", "color": "#888888",
                "lineHeight": "1.5", "padding": "6px 10px 8px",
                "borderTop": "1px solid #1e1e1e",
            },
        )

        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#111111",
            plot_bgcolor="#111111",
            font=dict(color="#ffffff", size=11),
            title=dict(text=meta["label"], font=dict(color=colour, size=12)),
            margin=dict(l=50, r=10, t=35, b=40),
            xaxis=dict(gridcolor="#2a2a2a", showticklabels=True, color="#ffffff"),
            yaxis=dict(gridcolor="#2a2a2a", title=meta.get("unit", ""), color="#ffffff"),
            showlegend=False,
            height=230,
        )

        charts.append(dbc.Col(
            html.Div(className="chart-container", children=[
                dcc.Graph(figure=fig, config={"displayModeBar": False}),
                desc_div,
            ]),
            md=6, lg=4,
        ))

    return charts


@callback(
    Output("macro-refresh-status", "children"),
    Output("macro-data-store",     "data"),
    Input("macro-refresh-btn",     "n_clicks"),
    prevent_initial_call=True,
)
def refresh_macro(_):
    from frontend.api_client import admin_refresh_macro
    import time
    res = admin_refresh_macro()
    if "error" in res:
        return f"Refresh failed: {res['error']}", {}
    counts = res.get("results", {})
    total  = sum(counts.values())
    return f"Refreshed {total:,} macro observations.", {"ts": time.time()}
