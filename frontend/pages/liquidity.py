"""
frontend.pages.liquidity
========================
Page – Fed Liquidity Dashboard.

Sections
--------
1. Net Liquidity Tracker — WALCL - RRP - TGA time-series with QE/QT regime badge.
2. Money Supply Growth   — M1 and M2 side-by-side charts.
3. TGA Balance           — Treasury spending drawdown.
4. Implied Printing Rate — 4-week and 13-week rolling change on WALCL.
"""

from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from dash import Input, Output, callback, dcc, html

from frontend.api_client import get_liquidity, get_macro_series

dash.register_page(__name__, path="/liquidity", name="Fed Liquidity", title="Fed Liquidity")

_REGIME_COLOUR = {"QE": "#2ecc71", "QT": "#e94560", "NEUTRAL": "#f0c040"}
_REGIME_LABEL  = {
    "QE":      "QE — Fed Expanding",
    "QT":      "QT — Fed Tightening",
    "NEUTRAL": "Neutral",
}
_DAYS_MAP = {"1Y": 365, "2Y": 730, "5Y": 1825, "10Y": 3650}


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

layout = html.Div([
    html.Div([
        html.Span("Fed ", className="page-title"),
        html.Span("Liquidity Dashboard", className="page-title title-accent"),
    ], style={"marginBottom": "12px"}),

    # Cross-link to Macro Monitor
    dbc.Alert(
        [
            html.I(className="bi-info-circle me-2"),
            "Focused liquidity view. For the full picture — rates, inflation, employment, and all Fed policy series — visit the ",
            html.A("Macro Monitor", href="/macro",
                   style={"color": "#4a90e2", "fontWeight": "600"}),
            ".",
        ],
        color="dark",
        style={"border": "1px solid #2a2a2a", "fontSize": "0.85rem", "marginBottom": "16px",
               "background": "#1a1a1a", "color": "#aaaaaa"},
        dismissable=False,
    ),

    dcc.Store(id="liq-data-store", data={}),

    # Controls
    dbc.Row([
        dbc.Col([
            html.Div("Timeframe", className="threshold-label"),
            dbc.RadioItems(
                id="liq-timeframe",
                options=[{"label": k, "value": k} for k in _DAYS_MAP],
                value="5Y",
                inline=True,
                style={"color": "#ffffff"},
            ),
        ], md=8),
        dbc.Col([
            dbc.Button(
                [html.I(className="bi-arrow-clockwise me-2"), "Refresh FRED Data"],
                id="liq-refresh-btn", color="secondary", size="sm", outline=True,
                style={"float": "right"},
            ),
        ], md=4),
    ], className="mb-3"),

    dcc.Loading(html.Div(id="liq-refresh-status",
                         style={"fontSize": "0.82rem", "color": "#2ecc71", "marginBottom": "8px"})),

    # --- Section 1: Net Liquidity ---
    html.Div("Net Liquidity  (WALCL − Reverse Repo − TGA)", className="section-title"),
    dbc.Row([
        dbc.Col(html.Div(id="liq-regime-kpi"), md=3),
        dbc.Col(dcc.Loading(dcc.Graph(id="liq-net-chart", config={"displayModeBar": False}),
                            type="circle", color="#4a90e2"), md=9),
    ], className="g-3 mb-4"),

    # --- Section 2: Money Supply ---
    html.Div("Money Supply", className="section-title"),
    dbc.Row([
        dbc.Col(dcc.Loading(dcc.Graph(id="liq-m2-chart",  config={"displayModeBar": False}),
                            type="circle", color="#5ba3e8"), md=6),
        dbc.Col(dcc.Loading(dcc.Graph(id="liq-m1-chart",  config={"displayModeBar": False}),
                            type="circle", color="#3a78c9"), md=6),
    ], className="g-3 mb-4"),

    # --- Section 3: Components ---
    html.Div("Liquidity Components", className="section-title"),
    dbc.Row([
        dbc.Col(dcc.Loading(dcc.Graph(id="liq-walcl-chart", config={"displayModeBar": False}),
                            type="circle", color="#4a90e2"), md=4),
        dbc.Col(dcc.Loading(dcc.Graph(id="liq-rrp-chart",   config={"displayModeBar": False}),
                            type="circle", color="#e94560"), md=4),
        dbc.Col(dcc.Loading(dcc.Graph(id="liq-tga-chart",   config={"displayModeBar": False}),
                            type="circle", color="#c0392b"), md=4),
    ], className="g-3 mb-4"),
])


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

def _line_chart(title: str, dates, vals, colour: str, unit: str = "Billions USD",
                height: int = 260) -> go.Figure:
    fig = go.Figure()
    if dates and vals:
        fig.add_trace(go.Scatter(
            x=dates, y=vals, mode="lines",
            line=dict(color=colour, width=2),
            fill="tozeroy", fillcolor=colour, opacity=0.08,
            name=title,
        ))
    else:
        fig.add_annotation(text="No data — click Refresh",
                           xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
                           font=dict(color="#888888", size=11))
    fig.update_layout(
        template="plotly_dark", paper_bgcolor="#111111", plot_bgcolor="#111111",
        font=dict(color="#ffffff", size=11),
        title=dict(text=title, font=dict(color=colour, size=12)),
        margin=dict(l=50, r=10, t=35, b=35),
        xaxis=dict(gridcolor="#2a2a2a", color="#ffffff"),
        yaxis=dict(gridcolor="#2a2a2a", title=unit, color="#ffffff"),
        showlegend=False, height=height,
    )
    return fig


@callback(
    Output("liq-regime-kpi",   "children"),
    Output("liq-net-chart",    "figure"),
    Output("liq-walcl-chart",  "figure"),
    Output("liq-rrp-chart",    "figure"),
    Output("liq-tga-chart",    "figure"),
    Input("liq-timeframe",     "value"),
    Input("liq-data-store",    "data"),
)
def update_liquidity_charts(timeframe, _store):
    days = _DAYS_MAP.get(timeframe, 1825)
    liq = get_liquidity(days=days) or {}
    regime = liq.get("regime", "NEUTRAL")
    data   = liq.get("data", [])

    # Regime KPI
    rc = _REGIME_COLOUR.get(regime, "#f0c040")
    rl = _REGIME_LABEL.get(regime, regime)
    latest_nl = data[-1]["net_liquidity"] if data else None
    nl_str = f"${latest_nl:,.1f}B" if latest_nl is not None else "—"

    regime_kpi = html.Div(className="kpi-card", children=[
        html.Div("Net Liquidity", className="kpi-label"),
        html.Div(nl_str, className="kpi-value", style={"fontSize": "1.6rem", "color": "#4a90e2"}),
        html.Div(rl, style={"marginTop": "6px", "fontSize": "0.75rem", "fontWeight": "700",
                            "color": rc, "border": f"1px solid {rc}",
                            "borderRadius": "3px", "padding": "3px 8px", "display": "inline-block"}),
        html.Div("WALCL − RRP − TGA", style={"fontSize": "0.68rem", "color": "#888", "marginTop": "6px"}),
    ])

    # Net liquidity chart
    net_dates = [p["date"] for p in data]
    net_vals  = [p["net_liquidity"] for p in data]
    net_fig = _line_chart("Net Liquidity (Billions USD)", net_dates, net_vals, "#4a90e2", height=300)

    # Component charts
    walcl_data = get_macro_series("WALCL", days=days)
    rrp_data   = get_macro_series("RRPONTSYD", days=days)
    tga_data   = get_macro_series("WDTGAL", days=days)

    def _extract(d):
        if d and d.get("data"):
            pts = d["data"]
            return [p["date"] for p in pts], [p["value"] for p in pts]
        return [], []

    w_d, w_v = _extract(walcl_data)
    r_d, r_v = _extract(rrp_data)
    t_d, t_v = _extract(tga_data)

    return (
        regime_kpi,
        net_fig,
        _line_chart("Fed Total Assets (WALCL)", w_d, w_v, "#4a90e2"),
        _line_chart("Overnight Reverse Repo",  r_d, r_v, "#e94560"),
        _line_chart("Treasury General Account (TGA)", t_d, t_v, "#c0392b"),
    )


@callback(
    Output("liq-m2-chart", "figure"),
    Output("liq-m1-chart", "figure"),
    Input("liq-timeframe", "value"),
    Input("liq-data-store", "data"),
)
def update_money_supply_charts(timeframe, _store):
    days = _DAYS_MAP.get(timeframe, 1825)
    m2 = get_macro_series("M2SL", days=days)
    m1 = get_macro_series("M1SL", days=days)

    def _fig(series_data, title, colour):
        if series_data and series_data.get("data"):
            pts = series_data["data"]
            return _line_chart(title, [p["date"] for p in pts], [p["value"] for p in pts], colour)
        return _line_chart(title, [], [], colour)

    return (
        _fig(m2, "M2 Money Supply (Billions USD)", "#5ba3e8"),
        _fig(m1, "M1 Money Supply (Billions USD)", "#3a78c9"),
    )


@callback(
    Output("liq-refresh-status", "children"),
    Output("liq-data-store",     "data"),
    Input("liq-refresh-btn",     "n_clicks"),
    prevent_initial_call=True,
)
def refresh_liquidity(_):
    from frontend.api_client import admin_refresh_macro
    import time
    res = admin_refresh_macro()
    if "error" in res:
        return f"Refresh failed: {res['error']}", {}
    counts = res.get("results", {})
    total = sum(counts.values())
    return f"Refreshed {total:,} FRED observations.", {"ts": time.time()}
