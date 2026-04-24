"""
frontend.pages.gap_scanner
===========================
Pre-Market Gap Regime Scanner page.

Displays a live gap regime classification for a list of tickers:
  - Overnight gap (%) and z-score
  - Regime classification (small gap / high-volume / extreme fade / opening drive)
  - Suggested strategies for each ticker
  - Relative volume (RVOL) indicator

Layout
------
1. Controls  — ticker input, scan button, interval selector
2. Regime Summary — count badges per regime type
3. Results table — sortable AG-Grid with all gap metrics
4. Regime guide card — explains each regime and its strategy routing
"""
from __future__ import annotations

import dash
import dash_ag_grid as dag
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, dcc, html, no_update
import plotly.graph_objects as go

from frontend.api_client import api_get

dash.register_page(
    __name__,
    path="/gap-scanner",
    name="Gap Scanner",
    title="Pre-Market Gap Scanner",
)

# ---------------------------------------------------------------------------
# Style constants
# ---------------------------------------------------------------------------

_BG      = "#000000"
_CARD_BG = "#0f0f0f"
_BORDER  = "#2a2a2a"
_TEXT    = "#cccccc"
_MUTED   = "#666666"
_ACCENT  = "#4a90e2"
_GREEN   = "#00e676"
_RED     = "#ff1744"
_YELLOW  = "#ffd740"
_ORANGE  = "#ff9100"

_card = {
    "backgroundColor": _CARD_BG,
    "border":          f"1px solid {_BORDER}",
    "borderRadius":    "6px",
    "padding":         "14px 18px",
    "marginBottom":    "12px",
}

_regime_colors: dict[str, str] = {
    "small_gap":          _ACCENT,
    "high_vol_gap":       _GREEN,
    "extreme_gap_fade":   _RED,
    "opening_drive":      _YELLOW,
    "no_trade":           _MUTED,
    "insufficient_data":  _MUTED,
}

_regime_labels: dict[str, str] = {
    "small_gap":          "Small Gap (S4+S5)",
    "high_vol_gap":       "High-Vol Gap (S6+S2)",
    "extreme_gap_fade":   "Extreme Fade (S1)",
    "opening_drive":      "Opening Drive (S3)",
    "no_trade":           "No Trade",
    "insufficient_data":  "Insufficient Data",
}

# ---------------------------------------------------------------------------
# Default tickers
# ---------------------------------------------------------------------------

_DEFAULT_TICKERS = "SPY,QQQ,AAPL,MSFT,NVDA,TSLA,AMZN,META,GOOGL,AMD"

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def layout() -> html.Div:
    return html.Div(
        style={"backgroundColor": _BG, "minHeight": "100vh", "padding": "20px 24px"},
        children=[
            dcc.Store(id="gap-scan-store"),

            # Header
            html.Div([
                html.H4(
                    "Pre-Market Gap Regime Scanner",
                    style={"color": _TEXT, "marginBottom": "4px"},
                ),
                html.P(
                    "Classify overnight gaps and route to the appropriate intraday strategy.",
                    style={"color": _MUTED, "fontSize": "0.85rem", "marginBottom": "16px"},
                ),
            ]),

            # Controls
            html.Div(style=_card, children=[
                dbc.Row([
                    dbc.Col([
                        html.Label("Tickers (comma-separated)",
                                   style={"color": _MUTED, "fontSize": "0.78rem"}),
                        dbc.Input(
                            id="gap-tickers-input",
                            value=_DEFAULT_TICKERS,
                            placeholder="SPY,QQQ,AAPL,...",
                            style={
                                "backgroundColor": "#1a1a1a",
                                "color": _TEXT,
                                "border": f"1px solid {_BORDER}",
                                "fontSize": "0.85rem",
                            },
                        ),
                    ], width=7),
                    dbc.Col([
                        html.Label("Bar Interval",
                                   style={"color": _MUTED, "fontSize": "0.78rem"}),
                        dbc.Select(
                            id="gap-interval-select",
                            options=[
                                {"label": "5 min", "value": "5m"},
                                {"label": "15 min", "value": "15m"},
                            ],
                            value="5m",
                            style={
                                "backgroundColor": "#1a1a1a",
                                "color": _TEXT,
                                "border": f"1px solid {_BORDER}",
                                "fontSize": "0.85rem",
                            },
                        ),
                    ], width=2),
                    dbc.Col([
                        html.Label("\u00a0", style={"color": _MUTED, "fontSize": "0.78rem"}),
                        dbc.Button(
                            "Scan Gaps",
                            id="gap-scan-btn",
                            color="primary",
                            style={"width": "100%"},
                        ),
                    ], width=2),
                    dbc.Col([
                        html.Label("\u00a0", style={"color": _MUTED, "fontSize": "0.78rem"}),
                        dbc.Spinner(
                            html.Div(id="gap-scan-status",
                                     style={"color": _MUTED, "fontSize": "0.78rem",
                                            "paddingTop": "6px"}),
                            size="sm", color="primary",
                        ),
                    ], width=1),
                ]),
            ]),

            # Regime summary badges
            html.Div(id="gap-regime-summary", style={"marginBottom": "12px"}),

            # Results table
            html.Div(style=_card, children=[
                html.Div(
                    "Gap Scan Results",
                    style={"color": _MUTED, "fontSize": "0.72rem",
                           "marginBottom": "8px", "textTransform": "uppercase",
                           "letterSpacing": "0.08em"},
                ),
                dag.AgGrid(
                    id="gap-results-grid",
                    rowData=[],
                    columnDefs=[
                        {"field": "ticker",           "headerName": "Ticker",     "width": 90},
                        {"field": "regime_label",     "headerName": "Regime",     "width": 180},
                        {"field": "total_gap_pct",    "headerName": "Gap %",      "width": 85,
                         "valueFormatter": {"function": "params.value != null ? params.value.toFixed(2) + '%' : ''"}},
                        {"field": "z_gap",            "headerName": "Z-Gap",      "width": 85,
                         "valueFormatter": {"function": "params.value != null ? params.value.toFixed(2) : ''"}},
                        {"field": "rvol",             "headerName": "RVOL",       "width": 80,
                         "valueFormatter": {"function": "params.value != null ? params.value.toFixed(2) + 'x' : 'N/A'"}},
                        {"field": "atr",              "headerName": "ATR",        "width": 80,
                         "valueFormatter": {"function": "params.value != null ? params.value.toFixed(3) : ''"}},
                        {"field": "sigma_overnight",  "headerName": "Sigma %",    "width": 90,
                         "valueFormatter": {"function": "params.value != null ? params.value.toFixed(3) + '%' : ''"}},
                        {"field": "strategies",       "headerName": "Strategies", "width": 130},
                        {"field": "error",            "headerName": "Note",       "width": 160},
                    ],
                    defaultColDef={
                        "sortable": True,
                        "resizable": True,
                        "cellStyle": {
                            "color": _TEXT,
                            "backgroundColor": _CARD_BG,
                            "fontSize": "0.82rem",
                        },
                    },
                    style={"height": "380px"},
                    dashGridOptions={
                        "domLayout": "normal",
                        "rowStyle": {"backgroundColor": _CARD_BG},
                        "headerHeight": 32,
                    },
                    className="ag-theme-alpine-dark",
                ),
            ]),

            # Regime guide
            html.Div(style=_card, children=[
                html.Div(
                    "Regime Routing Guide",
                    style={"color": _MUTED, "fontSize": "0.72rem",
                           "marginBottom": "10px", "textTransform": "uppercase",
                           "letterSpacing": "0.08em"},
                ),
                dbc.Row([
                    dbc.Col(_regime_card(k, v), width=6)
                    for k, v in {
                        "small_gap":        ("S4 + S5", "|z| < 1.0", "EMA cross + VWAP pullback"),
                        "high_vol_gap":     ("S6 + S2", "|z| >= 1.0 & RVOL >= 2x", "Gap continuation + ORB"),
                        "extreme_gap_fade": ("S1",      "|z| >= 1.5 & RVOL < 2x", "Fade failed extension"),
                        "opening_drive":    ("S3",      "Large gap, extension held", "30-min momentum"),
                    }.items()
                ]),
            ]),
        ],
    )


def _regime_card(regime_id: str, info: tuple[str, str, str]) -> html.Div:
    strats, condition, description = info
    color = _regime_colors.get(regime_id, _MUTED)
    return html.Div(
        style={
            "borderLeft": f"3px solid {color}",
            "paddingLeft": "10px",
            "marginBottom": "10px",
        },
        children=[
            html.Span(strats, style={"color": color, "fontWeight": "600",
                                     "fontSize": "0.85rem"}),
            html.Span(f"  {condition}", style={"color": _MUTED, "fontSize": "0.78rem",
                                                "marginLeft": "8px"}),
            html.Div(description, style={"color": _TEXT, "fontSize": "0.78rem",
                                          "marginTop": "2px"}),
        ],
    )


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

@callback(
    Output("gap-scan-store", "data"),
    Output("gap-scan-status", "children"),
    Input("gap-scan-btn", "n_clicks"),
    State("gap-tickers-input", "value"),
    State("gap-interval-select", "value"),
    prevent_initial_call=True,
)
def run_gap_scan(n_clicks, tickers_str, interval):
    if not tickers_str:
        return no_update, "No tickers entered"

    try:
        data = api_get(
            "/api/gap-scanner/scan",
            params={
                "tickers":              tickers_str,
                "bar_interval":         interval or "5m",
                "rvol_window_minutes":  30,
                "lookback_days":        30,
            },
        )
        count = len(data.get("results", []))
        return data, f"Scanned {count} tickers"
    except Exception as exc:
        return no_update, f"Error: {exc}"


@callback(
    Output("gap-results-grid", "rowData"),
    Output("gap-regime-summary", "children"),
    Input("gap-scan-store", "data"),
    prevent_initial_call=True,
)
def update_results(data):
    if not data or "results" not in data:
        return [], html.Div()

    results = data["results"]
    rows = []
    regime_counts: dict[str, int] = {}

    for r in results:
        regime = r.get("regime", "")
        regime_counts[regime] = regime_counts.get(regime, 0) + 1
        rows.append({
            "ticker":          r.get("ticker", ""),
            "regime_label":    _regime_labels.get(regime, regime),
            "total_gap_pct":   r.get("total_gap_pct"),
            "z_gap":           r.get("z_gap"),
            "rvol":            r.get("rvol"),
            "atr":             r.get("atr"),
            "sigma_overnight": r.get("sigma_overnight"),
            "strategies":      ", ".join(r.get("suggested_strategies", [])) or "-",
            "error":           r.get("error", "") or "",
        })

    # Summary badges
    badges = []
    for regime_id, count in sorted(regime_counts.items()):
        color = _regime_colors.get(regime_id, _MUTED)
        label = _regime_labels.get(regime_id, regime_id)
        badges.append(
            html.Span(
                f"{label}: {count}",
                style={
                    "backgroundColor": color + "22",
                    "border":          f"1px solid {color}",
                    "borderRadius":    "4px",
                    "color":           color,
                    "fontSize":        "0.78rem",
                    "padding":         "3px 10px",
                    "marginRight":     "8px",
                },
            )
        )

    return rows, html.Div(badges, style={"marginBottom": "4px"})
