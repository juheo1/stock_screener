"""
frontend.pages.intraday_monitor
================================
Intraday Monitor page — live 1-minute strategy signals during market hours.

Layout
------
Left panel:  Watchlist checklist, strategy checklist, monitor status,
             Start/Stop controls.
Right panel: Live 1-minute candlestick chart (selected ticker),
             Signal feed (last 50 signals, auto-refreshed),
             Intraday backtest launcher (date/ticker/strategy → run).

The page polls ``GET /api/intraday/signals`` and ``GET /api/intraday/status``
every 5 seconds via a ``dcc.Interval`` component.
"""
from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import requests
from dash import Input, Output, State, callback, dcc, html

from frontend.config import API_BASE_URL

dash.register_page(
    __name__,
    path="/intraday",
    name="Intraday Monitor",
    title="Intraday Monitor",
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_POLL_MS = 5_000  # 5-second polling interval

# Suggested default tickers for the watchlist input
_DEFAULT_WATCHLIST_SUGGESTION = "AAPL, MSFT, TSLA, NVDA, SPY"


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------

def _status_badge(state: str) -> html.Span:
    color = {"running": "success", "stopping": "warning", "stopped": "secondary"}.get(
        state, "secondary"
    )
    return dbc.Badge(state.upper(), color=color, className="ms-1")


# ---------------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------------

layout = dbc.Container(
    fluid=True,
    className="px-4 py-3",
    children=[
        # Auto-refresh interval
        dcc.Interval(id="intraday-poll-interval", interval=_POLL_MS, n_intervals=0),

        # ── Page header ──────────────────────────────────────────────────────
        html.H4(
            [html.I(className="bi-activity me-2"), "Intraday Monitor"],
            className="mb-3",
        ),

        dbc.Row([
            # ── Left control panel ──────────────────────────────────────────
            dbc.Col(
                width=3,
                children=[
                    # Monitor controls
                    dbc.Card(
                        className="mb-3",
                        children=dbc.CardBody([
                            html.H6("Monitor Controls", className="card-title"),
                            dbc.InputGroup(
                                className="mb-2",
                                children=[
                                    dbc.InputGroupText("Watchlist"),
                                    dbc.Textarea(
                                        id="intraday-watchlist-input",
                                        placeholder=_DEFAULT_WATCHLIST_SUGGESTION,
                                        rows=3,
                                        style={"fontSize": "0.8rem"},
                                    ),
                                ],
                            ),
                            dbc.Row([
                                dbc.Col(
                                    dbc.Button(
                                        [html.I(className="bi-play-fill me-1"), "Start"],
                                        id="intraday-start-btn",
                                        color="success",
                                        size="sm",
                                        className="w-100",
                                    ),
                                    width=6,
                                ),
                                dbc.Col(
                                    dbc.Button(
                                        [html.I(className="bi-stop-fill me-1"), "Stop"],
                                        id="intraday-stop-btn",
                                        color="danger",
                                        size="sm",
                                        className="w-100",
                                    ),
                                    width=6,
                                ),
                            ], className="g-2"),
                        ]),
                    ),

                    # Status card
                    dbc.Card(
                        className="mb-3",
                        children=dbc.CardBody([
                            html.H6("Status", className="card-title"),
                            html.Div(id="intraday-status-display"),
                        ]),
                    ),

                    # Ticker selector for chart
                    dbc.Card(
                        children=dbc.CardBody([
                            html.H6("Chart Ticker", className="card-title"),
                            dbc.Input(
                                id="intraday-chart-ticker",
                                placeholder="e.g. AAPL",
                                debounce=True,
                                size="sm",
                            ),
                        ]),
                    ),
                ],
            ),

            # ── Right main panel ────────────────────────────────────────────
            dbc.Col(
                width=9,
                children=[
                    # Live candlestick chart
                    dbc.Card(
                        className="mb-3",
                        children=dbc.CardBody([
                            html.H6("Live 1-Minute Chart", className="card-title"),
                            dcc.Graph(
                                id="intraday-live-chart",
                                config={"displayModeBar": False},
                                style={"height": "320px"},
                            ),
                        ]),
                    ),

                    # Signal feed
                    dbc.Card(
                        children=dbc.CardBody([
                            html.H6(
                                [
                                    "Signal Feed",
                                    html.Small(
                                        " (auto-refreshes every 5s)",
                                        className="text-muted ms-2",
                                    ),
                                ],
                                className="card-title",
                            ),
                            html.Div(
                                id="intraday-signal-feed",
                                style={
                                    "maxHeight": "280px",
                                    "overflowY": "auto",
                                    "fontSize": "0.8rem",
                                },
                            ),
                        ]),
                    ),
                ],
            ),
        ]),

        # Feedback toast
        dbc.Toast(
            id="intraday-feedback-toast",
            duration=3000,
            is_open=False,
            dismissable=True,
            style={"position": "fixed", "bottom": 20, "right": 20, "zIndex": 9999},
        ),
    ],
)


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

@callback(
    Output("intraday-status-display", "children"),
    Output("intraday-signal-feed", "children"),
    Output("intraday-live-chart", "figure"),
    Input("intraday-poll-interval", "n_intervals"),
    State("intraday-chart-ticker", "value"),
    prevent_initial_call=False,
)
def refresh_panel(n_intervals, chart_ticker):
    """Poll the API for status and recent signals."""
    status_children = _fetch_status_display()
    feed_children   = _fetch_signal_feed()
    chart_fig       = _fetch_chart(chart_ticker)
    return status_children, feed_children, chart_fig


@callback(
    Output("intraday-feedback-toast", "children"),
    Output("intraday-feedback-toast", "is_open"),
    Input("intraday-start-btn", "n_clicks"),
    Input("intraday-stop-btn", "n_clicks"),
    State("intraday-watchlist-input", "value"),
    prevent_initial_call=True,
)
def handle_controls(start_clicks, stop_clicks, watchlist_text):
    from dash import ctx as _ctx
    triggered = _ctx.triggered_id

    if triggered == "intraday-start-btn":
        tickers = _parse_tickers(watchlist_text)
        try:
            resp = requests.post(
                f"{API_BASE_URL}/api/intraday/start",
                json={"watchlist": tickers or None},
                timeout=10,
            )
            if resp.ok:
                return "Monitor started.", True
            return f"Start failed: {resp.text[:120]}", True
        except Exception as exc:
            return f"Request error: {exc}", True

    if triggered == "intraday-stop-btn":
        try:
            resp = requests.post(f"{API_BASE_URL}/api/intraday/stop", timeout=10)
            if resp.ok:
                return "Monitor stopped.", True
            return f"Stop failed: {resp.text[:120]}", True
        except Exception as exc:
            return f"Request error: {exc}", True

    return "", False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_status_display():
    """Fetch monitor status and render status lines."""
    try:
        resp = requests.get(f"{API_BASE_URL}/api/intraday/status", timeout=5)
        if not resp.ok:
            return html.Span("API unavailable", className="text-muted small")
        s = resp.json()
        state = s.get("state", "stopped")
        return html.Div([
            html.Div([html.Strong("State: "), _status_badge(state)]),
            html.Div(
                [html.Strong("Watchlist: "),
                 html.Span(", ".join(s.get("watchlist", [])) or "—", className="small")],
            ),
            html.Div([html.Strong("Last poll: "),
                      html.Span(s.get("last_poll") or "—", className="small text-muted")]),
            html.Div([html.Strong("Signals: "),
                      html.Span(str(s.get("signal_count", 0)))]),
        ], className="small")
    except Exception:
        return html.Span("Could not reach API.", className="text-danger small")


def _fetch_signal_feed():
    """Fetch recent signals and render a table."""
    try:
        resp = requests.get(
            f"{API_BASE_URL}/api/intraday/signals",
            params={"limit": 50},
            timeout=5,
        )
        if not resp.ok:
            return html.Span("No data.", className="text-muted small")
        signals = resp.json().get("signals", [])
    except Exception:
        return html.Span("Could not reach API.", className="text-danger small")

    if not signals:
        return html.Span("No signals yet.", className="text-muted small")

    rows = []
    for sig in signals:
        sig_type = sig.get("signal_type", 0)
        label    = "BUY"  if sig_type == 1  else "SELL"
        color    = "success" if sig_type == 1 else "danger"
        rows.append(
            html.Tr([
                html.Td(sig.get("signal_time", "")[:19], style={"whiteSpace": "nowrap"}),
                html.Td(html.Strong(sig.get("ticker", ""))),
                html.Td(dbc.Badge(label, color=color)),
                html.Td(sig.get("strategy_slug", ""), className="text-muted"),
                html.Td(f"${sig.get('close_price', 0):.2f}"),
            ])
        )

    return dbc.Table(
        [
            html.Thead(html.Tr([
                html.Th("Time"), html.Th("Ticker"), html.Th("Signal"),
                html.Th("Strategy"), html.Th("Price"),
            ])),
            html.Tbody(rows),
        ],
        bordered=False,
        hover=True,
        size="sm",
        className="mb-0",
    )


def _fetch_chart(ticker: str | None) -> go.Figure:
    """Fetch live 1m chart data and return a Plotly candlestick figure."""
    fig = go.Figure()
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(showgrid=False, color="#aaa"),
        yaxis=dict(showgrid=True, gridcolor="#2a2a2a", color="#aaa"),
        font=dict(color="#ddd"),
    )
    if not ticker:
        fig.add_annotation(
            text="Enter a ticker symbol to view live bars",
            xref="paper", yref="paper", x=0.5, y=0.5,
            showarrow=False, font=dict(color="#888", size=14),
        )
        return fig

    ticker = ticker.strip().upper()
    try:
        resp = requests.get(
            f"{API_BASE_URL}/api/intraday/chart/{ticker}", timeout=5
        )
        if not resp.ok:
            fig.add_annotation(
                text=f"No live data for {ticker}",
                xref="paper", yref="paper", x=0.5, y=0.5,
                showarrow=False, font=dict(color="#888", size=14),
            )
            return fig
        data = resp.json()
    except Exception:
        return fig

    fig.add_trace(
        go.Candlestick(
            x=data.get("timestamps", []),
            open=data.get("open", []),
            high=data.get("high", []),
            low=data.get("low", []),
            close=data.get("close", []),
            name=ticker,
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
        )
    )
    fig.update_layout(
        title=dict(text=f"{ticker} — 1m", font=dict(size=13), x=0.01),
        xaxis_rangeslider_visible=False,
    )
    return fig


def _parse_tickers(text: str | None) -> list[str]:
    if not text:
        return []
    return [t.strip().upper() for t in text.replace(",", " ").split() if t.strip()]
