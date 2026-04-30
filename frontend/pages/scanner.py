"""
frontend.pages.scanner
======================
Daily Strategy Scanner page.

Displays buy/sell signals detected across the ETF-constituent universe using
the same strategies as Technical Chart.  Users can drill into any result to
see the chart with indicators and backtest summary.

Layout sections
---------------
1. Controls  — strategy checklist, scan status, universe info, Run/Refresh buttons.
2. Results   — four AG-Grid tables: today buys, today sells, past buys, past sells.
3. Drill-down panel — chart + indicator overlays + backtest card (shown on row click).
"""
from __future__ import annotations

import json
from datetime import date

import dash
import dash_ag_grid as dag
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, callback, dcc, html, no_update

from frontend.api_client import (
    scanner_get_backtest,
    scanner_get_results,
    scanner_get_status,
    scanner_stop,
    scanner_trigger,
)
from frontend.strategy.engine import (
    StrategyError,
    compute_performance,
    get_chart_bundle,
    list_strategies,
    load_strategy,
    run_strategy,
)
from frontend.strategy.data import (
    INTERVAL_CFG,
    compute_indicator,
    compute_ma,
    fetch_ohlcv,
    get_source,
)
from frontend.strategy.chart import build_figure
from frontend.components.period_selector import (
    period_selector_row as _period_selector_row,
    slice_df_by_period as _slice_df_by_period,
    PERIOD_OPTIONS as _PERIOD_OPTIONS,
)

dash.register_page(
    __name__,
    path="/scanner",
    name="Strategy Scanner",
    title="Strategy Scanner",
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

_card_style = {
    "backgroundColor": _CARD_BG,
    "border": f"1px solid {_BORDER}",
    "borderRadius": "6px",
    "padding": "14px 18px",
    "marginBottom": "12px",
}
_section_hdr = {
    "color": _MUTED,
    "fontSize": "0.72rem",
    "fontWeight": 700,
    "letterSpacing": "0.10em",
    "marginBottom": "8px",
}

# ---------------------------------------------------------------------------
# AG Grid column definitions
# ---------------------------------------------------------------------------

_SIGNAL_COLS = [
    {"field": "ticker",               "headerName": "Ticker",     "width": 90,  "sortable": True, "filter": True},
    {"field": "strategy_display_name","headerName": "Strategy",   "width": 160, "sortable": True, "filter": True},
    {"field": "win_rate_pct",         "headerName": "Win %",      "width": 80,  "sortable": True, "filter": "agNumberColumnFilter",
     "valueFormatter": {"function": "params.value != null ? params.value.toFixed(1) + '%' : '—'"}},
    {"field": "trade_count",          "headerName": "Trades",     "width": 80,  "sortable": True, "filter": "agNumberColumnFilter"},
    {"field": "signal_date",          "headerName": "Date",       "width": 110, "sortable": True},
    {"field": "close_price",          "headerName": "Price",      "width": 90,  "sortable": True, "filter": "agNumberColumnFilter",
     "valueFormatter": {"function": "params.value != null ? '$' + params.value.toFixed(2) : ''"}},
    {"field": "days_ago",             "headerName": "Days Ago",   "width": 80,  "sortable": True, "filter": "agNumberColumnFilter"},
    {"field": "source_etfs_str",      "headerName": "ETFs",       "flex": 1,    "sortable": False, "filter": True},
]


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def layout() -> html.Div:
    all_strategies = _get_strategy_options()
    daily_strategies = [s for s in all_strategies if s.get("timeframe", "daily") == "daily"]
    _DEFAULT_ON = {"ma_crossover", "mean_reversion"}
    default_selected = [s["value"] for s in daily_strategies if s["value"] in _DEFAULT_ON]

    return html.Div(
        style={"backgroundColor": _BG, "minHeight": "100vh", "padding": "16px",
               "fontFamily": "'Inter', 'Segoe UI', system-ui, sans-serif"},
        children=[
            # ── Stores ──────────────────────────────────────────────
            dcc.Store(id="scanner-status-store"),
            dcc.Store(id="scanner-results-store"),
            dcc.Store(id="scanner-selected-row-store"),
            dcc.Store(id="scanner-active-job-store"),   # job_id currently being polled
            dcc.Store(id="scanner-all-strategies-store",
                      data=all_strategies),             # full strategy list for filtering
            # scanner-period-store lives inside the period selector row below
            dcc.Interval(id="scanner-poll-interval", interval=5000, n_intervals=0,
                         disabled=True),

            # ── Confirmation dialogs ─────────────────────────────────
            dcc.ConfirmDialog(
                id="scanner-confirm-dialog",
                message=(
                    "This will delete existing results for today and run a full "
                    "recompute across all tickers and strategies.\n\n"
                    "This may take several minutes. Continue?"
                ),
            ),
            dcc.ConfirmDialog(
                id="scanner-stop-dialog",
                message=(
                    "This will stop any currently running scan operation.\n\n"
                    "Partial results will NOT be saved. Continue?"
                ),
            ),

            # ── Page header ─────────────────────────────────────────
            html.H4(
                "Daily Strategy Scanner",
                style={"color": "#ffffff", "fontWeight": 700, "marginBottom": "16px"},
            ),

            # ── Controls card ────────────────────────────────────────
            html.Div(style=_card_style, children=[
                dbc.Row([
                    # Strategy type selector + checklist
                    dbc.Col([
                        dbc.Row([
                            dbc.Col([
                                html.Div("STRATEGY TYPE", style=_section_hdr),
                                dbc.RadioItems(
                                    id="scanner-timeframe-radio",
                                    options=[
                                        {"label": "Daily",    "value": "daily"},
                                        {"label": "Intraday", "value": "intraday"},
                                        {"label": "All",      "value": "all"},
                                    ],
                                    value="daily",
                                    inline=True,
                                    labelStyle={"marginRight": "14px", "color": _TEXT,
                                                "fontSize": "0.85rem"},
                                    inputStyle={"marginRight": "4px"},
                                ),
                            ], width="auto"),
                        ], className="mb-2"),
                        html.Div("STRATEGIES", style=_section_hdr),
                        dbc.Checklist(
                            id="scanner-strategy-checklist",
                            options=daily_strategies,
                            value=default_selected,
                            inline=True,
                            labelStyle={"marginRight": "14px", "color": _TEXT,
                                        "fontSize": "0.85rem"},
                            inputStyle={"marginRight": "4px"},
                        ),
                    ], md=7),

                    # Status + actions
                    dbc.Col([
                        html.Div(id="scanner-status-display",
                                 style={"color": _TEXT, "fontSize": "0.84rem",
                                        "marginBottom": "8px"}),
                        dbc.ButtonGroup([
                            dbc.Button(
                                [html.I(className="bi-play-circle me-1"), "Run New Scan Now"],
                                id="scanner-run-btn",
                                color="primary", size="sm",
                            ),
                            dbc.Button(
                                [html.I(className="bi-arrow-clockwise me-1"), "Refresh"],
                                id="scanner-refresh-btn",
                                color="secondary", size="sm",
                            ),
                            dbc.Button(
                                [html.I(className="bi-stop-circle me-1"), "Stop"],
                                id="scanner-stop-btn",
                                color="danger", size="sm",
                            ),
                        ]),
                        html.Div(id="scanner-trigger-feedback",
                                 style={"color": _MUTED, "fontSize": "0.78rem",
                                        "marginTop": "6px"}),
                    ], md=5, className="text-md-end"),
                ]),
            ]),

            # ── Filters card ───────────────────────────────────────────
            html.Div(style=_card_style, children=[
                html.Div(
                    id="scanner-filter-hdr",
                    style={
                        "cursor": "pointer",
                        "display": "flex",
                        "justifyContent": "space-between",
                        "alignItems": "center",
                        "marginBottom": "0px",
                    },
                    children=[
                        html.Span("FILTERS", style=_section_hdr | {"marginBottom": "0px"}),
                        html.I(
                            className="bi-chevron-right",
                            id="scanner-filter-hdr-icon",
                            style={"color": _MUTED},
                        ),
                    ],
                ),
                dbc.Collapse(
                    id="scanner-filter-collapse",
                    is_open=False,
                    children=[
                        html.Div(style={"marginTop": "10px"}, children=[
                            dbc.Row([
                                dbc.Col([
                                    html.Label("Min Win Rate (%)",
                                               style={"color": _MUTED, "fontSize": "0.78rem"}),
                                    dbc.Input(
                                        id="scanner-filter-min-winrate",
                                        type="number", min=0, max=100, step=1,
                                        placeholder="e.g. 50",
                                        size="sm",
                                        style={"backgroundColor": "#1a1a1a",
                                               "color": _TEXT, "border": f"1px solid {_BORDER}"},
                                    ),
                                ], md=2),
                                dbc.Col([
                                    html.Label("Min Trades",
                                               style={"color": _MUTED, "fontSize": "0.78rem"}),
                                    dbc.Input(
                                        id="scanner-filter-min-trades",
                                        type="number", min=0, step=1,
                                        placeholder="e.g. 5",
                                        size="sm",
                                        style={"backgroundColor": "#1a1a1a",
                                               "color": _TEXT, "border": f"1px solid {_BORDER}"},
                                    ),
                                ], md=2),
                                dbc.Col([
                                    html.Label("Ticker",
                                               style={"color": _MUTED, "fontSize": "0.78rem"}),
                                    dbc.Input(
                                        id="scanner-filter-ticker",
                                        type="text",
                                        placeholder="e.g. AAPL",
                                        size="sm",
                                        debounce=True,
                                        style={"backgroundColor": "#1a1a1a",
                                               "color": _TEXT, "border": f"1px solid {_BORDER}"},
                                    ),
                                ], md=2),
                                dbc.Col([
                                    html.Label("Max Days Ago",
                                               style={"color": _MUTED, "fontSize": "0.78rem"}),
                                    dbc.Input(
                                        id="scanner-filter-max-days-ago",
                                        type="number", min=0, step=1,
                                        placeholder="e.g. 3",
                                        size="sm",
                                        style={"backgroundColor": "#1a1a1a",
                                               "color": _TEXT, "border": f"1px solid {_BORDER}"},
                                    ),
                                ], md=2),
                                dbc.Col([
                                    html.Label("ETF",
                                               style={"color": _MUTED, "fontSize": "0.78rem"}),
                                    dbc.Input(
                                        id="scanner-filter-etf",
                                        type="text",
                                        placeholder="e.g. SPY",
                                        size="sm",
                                        debounce=True,
                                        style={"backgroundColor": "#1a1a1a",
                                               "color": _TEXT, "border": f"1px solid {_BORDER}"},
                                    ),
                                ], md=2),
                                dbc.Col([
                                    html.Label("\u00a0",
                                               style={"color": _MUTED, "fontSize": "0.78rem"}),
                                    dbc.Button(
                                        "Clear Filters",
                                        id="scanner-filter-clear-btn",
                                        color="outline-secondary", size="sm",
                                        style={"width": "100%"},
                                    ),
                                ], md=2),
                            ]),
                        ]),
                    ],
                ),
            ]),

            # ── Result tables ─────────────────────────────────────────
            _collapsible_table(
                header_id="scanner-latest-buy-hdr",
                collapse_id="scanner-latest-buy-collapse",
                grid_id="scanner-grid-latest-buy",
                title_id="scanner-latest-buy-title",
                default_open=True,
                accent_color=_GREEN,
            ),
            _collapsible_table(
                header_id="scanner-latest-sell-hdr",
                collapse_id="scanner-latest-sell-collapse",
                grid_id="scanner-grid-latest-sell",
                title_id="scanner-latest-sell-title",
                default_open=True,
                accent_color=_RED,
            ),
            _collapsible_table(
                header_id="scanner-past-buy-hdr",
                collapse_id="scanner-past-buy-collapse",
                grid_id="scanner-grid-past-buy",
                title_id="scanner-past-buy-title",
                default_open=False,
                accent_color="#40c080",
            ),
            _collapsible_table(
                header_id="scanner-past-sell-hdr",
                collapse_id="scanner-past-sell-collapse",
                grid_id="scanner-grid-past-sell",
                title_id="scanner-past-sell-title",
                default_open=False,
                accent_color="#c04040",
            ),

            # ── Drill-down panel ──────────────────────────────────────
            html.Div(
                id="scanner-drilldown-panel",
                style={"display": "none"},
                children=[
                    html.Hr(style={"borderColor": _BORDER, "margin": "16px 0"}),
                    _period_selector_row("scanner"),
                    dbc.Row([
                        # Chart
                        dbc.Col([
                            dcc.Graph(
                                id="scanner-drilldown-chart",
                                config={"displayModeBar": False},
                                style={"height": "420px"},
                            ),
                        ], md=8),
                        # Info cards
                        dbc.Col([
                            html.Div(id="scanner-drilldown-signal-card",
                                     style={**_card_style, "marginBottom": "8px"}),
                            html.Div(id="scanner-drilldown-backtest-card",
                                     style=_card_style),
                            # Track button + feedback
                            html.Div(style={"marginTop": "8px"}, children=[
                                dbc.Button(
                                    "Track This Signal",
                                    id="scanner-track-btn",
                                    color="success",
                                    size="sm",
                                    style={"width": "100%"},
                                ),
                                html.Div(id="scanner-track-feedback",
                                         style={"marginTop": "6px", "fontSize": "0.82rem"}),
                            ]),
                        ], md=4),
                    ]),
                ],
            ),
        ],
    )


def _collapsible_table(
    *,
    header_id: str,
    collapse_id: str,
    grid_id: str,
    title_id: str,
    default_open: bool,
    accent_color: str,
) -> html.Div:
    return html.Div(style={"marginBottom": "10px"}, children=[
        # Header (click to toggle)
        html.Div(
            id=header_id,
            style={
                "backgroundColor": "#111111",
                "border": f"1px solid {_BORDER}",
                "borderRadius": "4px",
                "padding": "8px 14px",
                "cursor": "pointer",
                "display": "flex",
                "justifyContent": "space-between",
                "alignItems": "center",
            },
            children=[
                html.Span(
                    id=title_id,
                    style={"color": accent_color, "fontWeight": 600,
                           "fontSize": "0.90rem"},
                ),
                html.I(
                    className="bi-chevron-down" if default_open else "bi-chevron-right",
                    id=f"{header_id}-icon",
                    style={"color": _MUTED},
                ),
            ],
        ),
        dbc.Collapse(
            id=collapse_id,
            is_open=default_open,
            children=[
                html.Div(style={"marginTop": "4px"}, children=[
                    dag.AgGrid(
                        id=grid_id,
                        columnDefs=_SIGNAL_COLS,
                        rowData=[],
                        defaultColDef={"resizable": True, "sortable": True},
                        dashGridOptions={
                            "rowSelection": "single",
                            "suppressCellFocus": True,
                            "domLayout": "autoHeight",
                        },
                        style={"height": None},
                        className="ag-theme-alpine-dark",
                    ),
                ]),
            ],
        ),
    ])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_strategy_options() -> list[dict]:
    """Build checklist options from the shared strategy registry."""
    try:
        strategies = list_strategies()
        return [
            {
                "label": s["display_name"],
                "value": s["name"],
                "builtin": s["is_builtin"],
            }
            for s in strategies
        ]
    except Exception:
        return []


def _fmt_signals(signals: list[dict]) -> list[dict]:
    """Convert API signal items to AG Grid row data."""
    rows = []
    for s in signals:
        wr = s.get("win_rate")
        rows.append({
            "ticker":               s.get("ticker", ""),
            "strategy":             s.get("strategy", ""),
            "strategy_display_name": s.get("strategy_display_name", s.get("strategy", "")),
            "win_rate_pct":         round(wr * 100, 1) if wr is not None else None,
            "trade_count":          s.get("trade_count"),
            "signal_type":          s.get("signal_type", 0),
            "signal_date":          s.get("signal_date", ""),
            "close_price":          s.get("close_price"),
            "days_ago":             s.get("days_ago", 0),
            "source_etfs_str":      ", ".join(s.get("source_etfs", [])),
            "source_etfs":          s.get("source_etfs", []),
            "scan_signal_id":       s.get("scan_signal_id"),
        })
    return rows


def _apply_filters(
    signals: list[dict],
    min_wr: float | None,
    min_trades: int | None,
    ticker_filter: str | None,
    max_days: int | None,
    etf_filter: str | None,
) -> list[dict]:
    """Filter signal dicts before formatting for the grid."""
    result = signals
    if min_wr is not None:
        threshold = min_wr / 100.0
        result = [s for s in result
                  if s.get("win_rate") is not None and s["win_rate"] >= threshold]
    if min_trades is not None:
        result = [s for s in result
                  if s.get("trade_count") is not None and s["trade_count"] >= min_trades]
    if ticker_filter:
        t = ticker_filter.strip().upper()
        result = [s for s in result if t in s.get("ticker", "").upper()]
    if max_days is not None:
        result = [s for s in result if s.get("days_ago", 0) <= max_days]
    if etf_filter:
        e = etf_filter.strip().upper()
        result = [s for s in result
                  if any(e in etf.upper() for etf in s.get("source_etfs", []))]
    return result


def _status_badge(status: str | None) -> html.Span:
    color_map = {
        "COMPLETED": _GREEN,
        "RUNNING":   "#ffcc00",
        "PENDING":   "#ffcc00",
        "FAILED":    _RED,
        "SKIPPED":   _ACCENT,
        "STOPPED":   "#ff9100",
    }
    color = color_map.get(status or "", _MUTED)
    return html.Span(
        f"● {status or 'Unknown'}",
        style={"color": color, "fontWeight": 600},
    )


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

# ── On page load and Refresh button: fetch latest scan status ────────────

@callback(
    Output("scanner-status-store", "data"),
    Output("scanner-results-store", "data"),
    Input("scanner-refresh-btn", "n_clicks"),
    Input("scanner-poll-interval", "n_intervals"),
    State("scanner-active-job-store", "data"),
    prevent_initial_call=False,
)
def load_scan_data(n_refresh, n_intervals, active_job_id):
    # When an active job is being tracked, poll its specific status.
    # Results always show the latest completed scan regardless of job being tracked.
    status  = scanner_get_status(job_id=active_job_id)
    results = scanner_get_results()
    return status, results


# ── Update status display ────────────────────────────────────────────────

@callback(
    Output("scanner-status-display", "children"),
    Output("scanner-poll-interval", "disabled"),
    Input("scanner-status-store", "data"),
)
def update_status_display(status):
    if status is None:
        return [
            html.Span("No scan data available. ", style={"color": _MUTED}),
            html.Span("Run a scan to see results.", style={"color": _MUTED, "fontSize": "0.78rem"}),
        ], True

    is_running = status.get("is_running", False) or status.get("status") in ("RUNNING", "PENDING")
    scan_date  = status.get("scan_date", "")
    stat       = status.get("status", "")
    n_tickers  = status.get("ticker_count", 0)
    n_signals  = status.get("signal_count", 0)
    completed  = status.get("completed_at") or ""
    etfs       = status.get("universe_etfs", [])

    parts = [
        html.Span("Status: "),
        _status_badge(stat),
        html.Span(f"  |  Date: {scan_date}", style={"color": _MUTED}),
    ]
    if n_tickers:
        parts.append(html.Span(
            f"  |  {n_tickers} tickers from {len(etfs)} ETFs  |  {n_signals} signals",
            style={"color": _MUTED},
        ))
    if completed:
        parts.append(html.Span(f"  |  Completed: {completed[:16]} UTC",
                               style={"color": _MUTED, "fontSize": "0.78rem"}))

    # Enable polling while running
    return parts, not is_running


# ── Update result tables ──────────────────────────────────────────────────

@callback(
    Output("scanner-latest-buy-title",  "children"),
    Output("scanner-latest-sell-title", "children"),
    Output("scanner-past-buy-title",    "children"),
    Output("scanner-past-sell-title",   "children"),
    Output("scanner-grid-latest-buy",   "rowData"),
    Output("scanner-grid-latest-sell",  "rowData"),
    Output("scanner-grid-past-buy",     "rowData"),
    Output("scanner-grid-past-sell",    "rowData"),
    Input("scanner-results-store", "data"),
    Input("scanner-filter-min-winrate", "value"),
    Input("scanner-filter-min-trades", "value"),
    Input("scanner-filter-ticker", "value"),
    Input("scanner-filter-max-days-ago", "value"),
    Input("scanner-filter-etf", "value"),
)
def update_tables(results, min_wr, min_trades, ticker_filter, max_days, etf_filter):
    empty = []
    if not results:
        return (
            "Latest Buy Signals (0)", "Latest Sell Signals (0)",
            "Past Buy Signals (0)",   "Past Sell Signals (0)",
            empty, empty, empty, empty,
        )

    ltd = results.get("latest_trading_date", "")
    date_label = f" ({ltd})" if ltd else ""

    lb = _apply_filters(results.get("latest_buys",  []), min_wr, min_trades, ticker_filter, max_days, etf_filter)
    ls = _apply_filters(results.get("latest_sells", []), min_wr, min_trades, ticker_filter, max_days, etf_filter)
    pb = _apply_filters(results.get("past_buys",    []), min_wr, min_trades, ticker_filter, max_days, etf_filter)
    ps = _apply_filters(results.get("past_sells",   []), min_wr, min_trades, ticker_filter, max_days, etf_filter)

    return (
        f"Latest Buy Signals{date_label} ({len(lb)})",
        f"Latest Sell Signals{date_label} ({len(ls)})",
        f"Past Buy Signals — last 10 days ({len(pb)})",
        f"Past Sell Signals — last 10 days ({len(ps)})",
        _fmt_signals(lb), _fmt_signals(ls),
        _fmt_signals(pb), _fmt_signals(ps),
    )


# ── Collapse toggles ──────────────────────────────────────────────────────

def _make_toggle_callback(header_id, collapse_id, icon_id):
    @callback(
        Output(collapse_id,  "is_open"),
        Output(icon_id,      "className"),
        Input(header_id,     "n_clicks"),
        State(collapse_id,   "is_open"),
        prevent_initial_call=True,
    )
    def _toggle(n, is_open):
        new_open = not is_open
        icon     = "bi-chevron-down" if new_open else "bi-chevron-right"
        return new_open, icon


_make_toggle_callback("scanner-filter-hdr",       "scanner-filter-collapse",       "scanner-filter-hdr-icon")
_make_toggle_callback("scanner-latest-buy-hdr",  "scanner-latest-buy-collapse",  "scanner-latest-buy-hdr-icon")
_make_toggle_callback("scanner-latest-sell-hdr", "scanner-latest-sell-collapse", "scanner-latest-sell-hdr-icon")
_make_toggle_callback("scanner-past-buy-hdr",   "scanner-past-buy-collapse",   "scanner-past-buy-hdr-icon")
_make_toggle_callback("scanner-past-sell-hdr",  "scanner-past-sell-collapse",  "scanner-past-sell-hdr-icon")


# ── Clear filters ────────────────────────────────────────────────────────

@callback(
    Output("scanner-filter-min-winrate", "value"),
    Output("scanner-filter-min-trades", "value"),
    Output("scanner-filter-ticker", "value"),
    Output("scanner-filter-max-days-ago", "value"),
    Output("scanner-filter-etf", "value"),
    Input("scanner-filter-clear-btn", "n_clicks"),
    prevent_initial_call=True,
)
def clear_filters(_n):
    return None, None, None, None, None


# ── Timeframe radio → update strategy checklist options ──────────────────

@callback(
    Output("scanner-strategy-checklist", "options"),
    Output("scanner-strategy-checklist", "value"),
    Input("scanner-timeframe-radio", "value"),
    State("scanner-all-strategies-store", "data"),
    State("scanner-strategy-checklist", "value"),
    prevent_initial_call=True,
)
def update_checklist_for_timeframe(timeframe, all_strats, current_selected):
    if not all_strats:
        return [], []
    if timeframe == "all":
        filtered = all_strats
    else:
        filtered = [s for s in all_strats if s.get("timeframe", "daily") == timeframe]
    available = {s["value"] for s in filtered}
    # Keep currently selected strategies that are still in the filtered list
    new_selected = [v for v in (current_selected or []) if v in available]
    return filtered, new_selected


# ── Manual scan trigger ───────────────────────────────────────────────────
# Step 1: Button click → open confirmation dialog

@callback(
    Output("scanner-confirm-dialog", "displayed"),
    Input("scanner-run-btn", "n_clicks"),
    prevent_initial_call=True,
)
def open_confirm_dialog(n_clicks):
    return bool(n_clicks)


# Step 2: Dialog confirmed → call API with force=True

@callback(
    Output("scanner-trigger-feedback", "children"),
    Output("scanner-poll-interval",    "disabled", allow_duplicate=True),
    Output("scanner-active-job-store", "data"),
    Input("scanner-confirm-dialog",    "submit_n_clicks"),
    State("scanner-strategy-checklist", "value"),
    State("scanner-timeframe-radio",    "value"),
    prevent_initial_call=True,
)
def execute_forced_scan(submit_n_clicks, selected_strategies, timeframe):
    if not submit_n_clicks:
        return no_update, no_update, no_update

    result = scanner_trigger(
        strategy_slugs=selected_strategies or None,
        force=True,
        timeframe=timeframe or "daily",
    )

    if result is None:
        return (
            html.Span("Scan already running or could not start.",
                      style={"color": _RED}),
            True,
            no_update,
        )

    job_id = result.get("job_id", "?")

    return (
        html.Span(
            f"New scan started (job {job_id}). Polling for updates...",
            style={"color": _GREEN},
        ),
        False,   # enable polling
        job_id,  # store job_id so load_scan_data polls the right job
    )


# ── Stop scan ────────────────────────────────────────────────────────────
# Step 1: Stop button → open confirmation dialog

@callback(
    Output("scanner-stop-dialog", "displayed"),
    Input("scanner-stop-btn", "n_clicks"),
    prevent_initial_call=True,
)
def open_stop_dialog(n_clicks):
    return bool(n_clicks)


# Step 2: Dialog confirmed → call stop API

@callback(
    Output("scanner-trigger-feedback", "children", allow_duplicate=True),
    Input("scanner-stop-dialog", "submit_n_clicks"),
    prevent_initial_call=True,
)
def execute_stop(submit_n_clicks):
    if not submit_n_clicks:
        return no_update

    result = scanner_stop()
    if result is None:
        return html.Span("Could not send stop signal — is the API running?",
                         style={"color": _RED})

    return html.Span(
        result.get("message", "Stop signal sent."),
        style={"color": "#ff9100"},
    )


# ── Row selection → drill-down ────────────────────────────────────────────

@callback(
    Output("scanner-selected-row-store", "data"),
    Input("scanner-grid-latest-buy",  "selectedRows"),
    Input("scanner-grid-latest-sell", "selectedRows"),
    Input("scanner-grid-past-buy",    "selectedRows"),
    Input("scanner-grid-past-sell",   "selectedRows"),
    prevent_initial_call=True,
)
def capture_selected_row(tb, ts, pb, ps):
    """Store the selected row from whichever table fired the callback."""
    triggered = dash.ctx.triggered_id
    category_map = {
        "scanner-grid-latest-buy":  "latest-buy",
        "scanner-grid-latest-sell": "latest-sell",
        "scanner-grid-past-buy":    "past-buy",
        "scanner-grid-past-sell":   "past-sell",
    }
    grid_map = {
        "scanner-grid-latest-buy":  tb,
        "scanner-grid-latest-sell": ts,
        "scanner-grid-past-buy":    pb,
        "scanner-grid-past-sell":   ps,
    }
    rows = grid_map.get(triggered)
    if rows:
        row = dict(rows[0])
        row["signal_category"] = category_map.get(triggered, "manual")
        return row
    return no_update


@callback(
    Output("scanner-drilldown-panel",         "style"),
    Output("scanner-drilldown-chart",         "figure"),
    Output("scanner-drilldown-signal-card",   "children"),
    Output("scanner-drilldown-backtest-card", "children"),
    Output("scanner-track-btn",               "children"),
    Output("scanner-track-btn",               "disabled"),
    Output("scanner-track-feedback",          "children"),
    Input("scanner-selected-row-store", "data"),
    Input("scanner-period-store",       "data"),
    prevent_initial_call=True,
)
def render_drilldown(row, period):
    """Render chart + signal info + backtest card for the selected row."""
    if not row:
        return {"display": "none"}, go.Figure(), [], [], "Track This Signal", False, ""

    ticker   = row.get("ticker", "")
    strategy = row.get("strategy", "")
    strategy_name = row.get("strategy_display_name", strategy)

    if not ticker or not strategy:
        return {"display": "none"}, go.Figure(), [], [], "Track This Signal", False, ""

    period = period or "1y"

    # ── Fetch OHLCV ─────────────────────────────────────────────────
    df = fetch_ohlcv(ticker, "1D")
    if df is not None and not df.empty:
        df = _slice_df_by_period(df, period)
    if df is None or df.empty:
        error_fig = _empty_fig(f"Could not fetch data for {ticker}")
        return {"display": "block"}, error_fig, _error_card("No data"), [], "Track This Signal", False, ""

    # ── Load strategy + resolve chart bundle ─────────────────────────
    computed_inds = []
    fill_betweens = []
    signals_series = None

    try:
        # Find strategy metadata (builtin flag)
        strat_meta = next(
            (s for s in list_strategies() if s["name"] == strategy),
            None,
        )
        is_builtin = strat_meta["is_builtin"] if strat_meta else False

        mod    = load_strategy(strategy, is_builtin=is_builtin)
        params = _get_default_params(mod)

        result = run_strategy(
            df=df,
            ticker=ticker,
            interval="1D",
            strategy_module=mod,
            params=params,
            get_source_fn=get_source,
            compute_ma_fn=compute_ma,
            compute_indicator_fn=compute_indicator,
        )
        signals_series = result.signals

        # Resolve chart bundle indicators
        bundle = get_chart_bundle(mod)
        if bundle:
            from frontend.pages.technical import _load_preset  # reuse existing loader
            if "preset" in bundle:
                preset = _load_preset(bundle["preset"])
                if preset:
                    bundle_inds = preset.get("indicators", [])
                    fill_betweens = preset.get("fill_betweens", [])
                else:
                    bundle_inds = bundle.get("indicators", [])
                    fill_betweens = bundle.get("fill_betweens", [])
            else:
                bundle_inds = bundle.get("indicators", [])
                fill_betweens = bundle.get("fill_betweens", [])

            for ind_spec in bundle_inds:
                try:
                    computed_inds.append(compute_indicator(df, ind_spec))
                except Exception:
                    pass

    except (StrategyError, Exception):
        pass  # Chart shown without strategy overlay

    # ── Build figure ─────────────────────────────────────────────────
    fig = build_figure(
        df=df,
        ticker=ticker,
        interval_key="1D",
        computed_inds=computed_inds,
        fill_betweens=fill_betweens,
        signals=signals_series,
    )

    # ── Signal info card ─────────────────────────────────────────────
    sig_type = row.get("signal_type")  # 1=BUY, -1=SELL (set by _fmt_signals)

    sig_label = "BUY" if sig_type == 1 else "SELL"
    sig_color = _GREEN if sig_type == 1 else _RED

    signal_card = [
        html.Div("SIGNAL DETAIL", style=_section_hdr),
        html.Div([
            html.Span("Ticker: ", style={"color": _MUTED, "fontSize": "0.82rem"}),
            html.Span(ticker, style={"color": "#ffffff", "fontWeight": 700,
                                     "fontSize": "1.0rem", "marginRight": "10px"}),
            html.Span(sig_label, style={"color": sig_color, "fontWeight": 700,
                                        "fontSize": "0.92rem",
                                        "border": f"1px solid {sig_color}",
                                        "padding": "1px 6px", "borderRadius": "3px"}),
        ], style={"marginBottom": "6px"}),
        html.Div([
            html.Span("Strategy: ", style={"color": _MUTED, "fontSize": "0.80rem"}),
            html.Span(strategy_name, style={"color": _TEXT, "fontSize": "0.82rem"}),
        ], style={"marginBottom": "4px"}),
        html.Div([
            html.Span("Date: ", style={"color": _MUTED, "fontSize": "0.80rem"}),
            html.Span(row.get("signal_date", ""), style={"color": _TEXT, "fontSize": "0.82rem"}),
        ], style={"marginBottom": "4px"}),
        html.Div([
            html.Span("Close: ", style={"color": _MUTED, "fontSize": "0.80rem"}),
            html.Span(
                f"${row.get('close_price', 0):.2f}" if row.get("close_price") else "—",
                style={"color": _TEXT, "fontSize": "0.82rem"},
            ),
        ], style={"marginBottom": "4px"}),
        html.Div([
            html.Span("ETFs: ", style={"color": _MUTED, "fontSize": "0.80rem"}),
            html.Span(row.get("source_etfs_str", ""), style={"color": _TEXT, "fontSize": "0.78rem"}),
        ]),
    ]

    # ── Backtest card ─────────────────────────────────────────────────
    if signals_series is not None:
        from frontend.strategy.backtest import run_backtest, backtest_to_dict
        from frontend.pages.technical import _build_perf_card
        spy_df = None
        try:
            spy_df = fetch_ohlcv("SPY", "1D")
            if spy_df is not None and not spy_df.empty:
                spy_df = _slice_df_by_period(spy_df, period)
        except Exception:
            pass
        bt = run_backtest(df, signals_series, spy_df=spy_df)
        perf = backtest_to_dict(bt)
        backtest_card = [
            html.Div("BACKTEST SUMMARY", style=_section_hdr),
            _build_perf_card(strategy_name, perf),
        ]
    else:
        backtest_card = [
            html.Div("BACKTEST SUMMARY", style=_section_hdr),
            html.Div("No backtest data available for this signal.",
                     style={"color": _MUTED, "fontSize": "0.82rem"}),
        ]

    # ── Check if signal already tracked ─────────────────────────────
    from frontend.api_client import trades_check
    scan_signal_id = row.get("scan_signal_id")
    if scan_signal_id:
        check = trades_check(scan_signal_id)
        if check and check.get("tracked"):
            track_label   = "Already Tracked"
            track_disabled = True
            track_feedback = html.Span(
                f"Tracked (id={check.get('trade_id')})",
                style={"color": "#4a9eff", "fontSize": "0.78rem"},
            )
        else:
            track_label    = "Track This Signal"
            track_disabled = False
            track_feedback = ""
    else:
        track_label    = "Track This Signal"
        track_disabled = False
        track_feedback = ""

    return {"display": "block"}, fig, signal_card, backtest_card, track_label, track_disabled, track_feedback


# ── Track signal callback ─────────────────────────────────────────────────

@callback(
    Output("scanner-track-feedback", "children", allow_duplicate=True),
    Output("scanner-track-btn",      "children",  allow_duplicate=True),
    Output("scanner-track-btn",      "disabled",  allow_duplicate=True),
    Input("scanner-track-btn",  "n_clicks"),
    State("scanner-selected-row-store", "data"),
    State("scanner-results-store",      "data"),
    prevent_initial_call=True,
)
def track_signal(n_clicks, row, results):
    """POST tracked trade to API when user clicks 'Track This Signal'."""
    if not n_clicks or not row:
        return no_update, no_update, no_update

    from frontend.api_client import trades_create, scanner_get_backtest

    ticker   = row.get("ticker", "")
    strategy = row.get("strategy", "")

    if not ticker or not strategy:
        return html.Span("No signal selected.", style={"color": "#ff4444"}), no_update, no_update

    # Get scan metadata from results store
    scan_date = (results or {}).get("scan_date", date.today().isoformat())
    job_id    = (results or {}).get("job_id")

    # Fetch backtest data for snapshot
    bt = scanner_get_backtest(ticker, strategy)
    bt_win_rate    = bt.get("win_rate")    if bt else None
    bt_trade_count = bt.get("trade_count") if bt else None
    bt_total_pnl   = bt.get("total_pnl")  if bt else None
    bt_avg_pnl     = bt.get("avg_pnl")    if bt else None

    payload = {
        "ticker":                ticker,
        "signal_side":           row.get("signal_type", 1),
        "strategy_slug":         strategy,
        "strategy_display_name": row.get("strategy_display_name", strategy),
        "signal_date":           row.get("signal_date", scan_date),
        "scan_date":             scan_date,
        "signal_category":       row.get("signal_category", "manual"),
        "source_etfs":           row.get("source_etfs", []),
        "days_ago":              row.get("days_ago", 0),
        "scan_signal_id":        row.get("scan_signal_id"),
        "scan_job_id":           job_id,
        "close_price":           row.get("close_price"),
        "bt_win_rate":           bt_win_rate,
        "bt_trade_count":        bt_trade_count,
        "bt_total_pnl":          bt_total_pnl,
        "bt_avg_pnl":            bt_avg_pnl,
    }

    result = trades_create(payload)
    if result is None:
        return (
            html.Span("Track failed — check API.", style={"color": "#ff4444"}),
            "Track This Signal", False,
        )

    side = "BUY" if row.get("signal_type", 1) == 1 else "SELL"
    feedback = html.Span(
        f"{ticker} {side} tracked (id={result.get('id')})",
        style={"color": "#00c896"},
    )
    return feedback, "Already Tracked", True


# ---------------------------------------------------------------------------
# Period selector callbacks
# ---------------------------------------------------------------------------

@callback(
    Output("scanner-period-store", "data"),
    [Input({"type": "scanner-period-btn", "index": p[1]}, "n_clicks")
     for p in _PERIOD_OPTIONS],
    prevent_initial_call=True,
)
def _scanner_set_period(*_):
    triggered = dash.ctx.triggered_id
    if isinstance(triggered, dict):
        return triggered.get("index", "1y")
    return "1y"


@callback(
    [Output({"type": "scanner-period-btn", "index": p[1]}, "outline") for p in _PERIOD_OPTIONS],
    [Output({"type": "scanner-period-btn", "index": p[1]}, "color")   for p in _PERIOD_OPTIONS],
    Input("scanner-period-store", "data"),
)
def _scanner_highlight_period(active: str):
    active = active or "1y"
    outlines = [p[1] != active for p in _PERIOD_OPTIONS]
    colors   = ["primary" if p[1] == active else "secondary" for p in _PERIOD_OPTIONS]
    return outlines + colors


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_default_params(mod) -> dict:
    params_spec = getattr(mod, "PARAMS", {})
    return {k: v["default"] for k, v in params_spec.items()}


def _empty_fig(message: str = "") -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        paper_bgcolor="#000000", plot_bgcolor="#000000",
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        annotations=[dict(
            text=message, xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(color="#666666", size=14),
        )],
        margin=dict(l=10, r=10, t=20, b=20),
    )
    return fig


def _error_card(message: str) -> list:
    return [html.Div(message, style={"color": _RED, "fontSize": "0.84rem"})]
