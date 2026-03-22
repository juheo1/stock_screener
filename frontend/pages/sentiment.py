"""
frontend.pages.sentiment
========================
Page – News & Sentiment Hub.

Sections
--------
1. Sentiment Gauges   — Fear/Greed score, VIX percentile, Put/Call ratio.
2. News Feed          — Filterable by category, NLP sentiment labels.
3. Natural Disasters  — M5.5+ earthquakes from USGS (last 7 days).
4. Ticker News        — Enter a ticker to pull headlines mentioning it.
"""

from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from dash import Input, Output, State, callback, dcc, html

from frontend.api_client import (
    get_earthquakes,
    get_news,
    get_news_for_ticker,
    get_sentiment_latest,
    refresh_earthquakes,
    refresh_news,
    refresh_sentiment,
)

dash.register_page(__name__, path="/sentiment", name="News & Sentiment", title="News & Sentiment")

_SENTIMENT_CATEGORIES = [
    {"label": "All",          "value": "all"},
    {"label": "Macro",        "value": "macro"},
    {"label": "Geopolitical", "value": "geopolitical"},
    {"label": "Financial",    "value": "financial"},
    {"label": "Disaster",     "value": "disaster"},
]

_LABEL_COLOUR = {"Bullish": "#2ecc71", "Bearish": "#e94560", "Neutral": "#f0c040"}


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

layout = html.Div([
    html.Div([
        html.Span("News & ", className="page-title"),
        html.Span("Sentiment Hub", className="page-title title-accent"),
    ], style={"marginBottom": "20px"}),

    dcc.Store(id="sent-data-store", data={}),
    dcc.Interval(id="sent-auto-refresh", interval=15 * 60 * 1000, n_intervals=0),  # 15 min

    # Refresh controls
    dbc.Row([
        dbc.Col([
            dbc.Button([html.I(className="bi-arrow-clockwise me-2"), "Refresh Sentiment"],
                       id="sent-refresh-btn", color="secondary", size="sm", outline=True),
            dbc.Button([html.I(className="bi-newspaper me-2"), "Refresh News"],
                       id="sent-news-refresh-btn", color="secondary", size="sm", outline=True,
                       className="ms-2",
                       title="Requires NEWSAPI_KEY in .env"),
            dbc.Button([html.I(className="bi-geo-alt me-2"), "Refresh Earthquakes"],
                       id="sent-quake-refresh-btn", color="secondary", size="sm", outline=True,
                       className="ms-2"),
        ], md=8),
        dbc.Col([
            html.Div(id="sent-refresh-status",
                     style={"fontSize": "0.80rem", "color": "#2ecc71", "textAlign": "right"}),
        ], md=4),
    ], className="mb-3"),

    # --- Section 1: Sentiment Gauges ---
    html.Div("Market Sentiment Gauges", className="section-title"),
    dcc.Loading(
        dbc.Row(id="sent-gauges-row", className="g-3 mb-4"),
        type="circle", color="#4a90e2",
    ),

    # --- Section 2: News Feed ---
    html.Div("News Feed", className="section-title"),
    html.Div([
        html.Span("Sentiment labels are determined by keyword analysis of headlines.  ", style={"color": "#888", "fontSize": "0.75rem"}),
        html.Span("Bullish", style={"color": "#2ecc71", "fontSize": "0.75rem", "fontWeight": "600"}),
        html.Span(" = positive market keywords  ·  ", style={"color": "#888", "fontSize": "0.75rem"}),
        html.Span("Bearish", style={"color": "#e94560", "fontSize": "0.75rem", "fontWeight": "600"}),
        html.Span(" = negative  ·  ", style={"color": "#888", "fontSize": "0.75rem"}),
        html.Span("Neutral", style={"color": "#f0c040", "fontSize": "0.75rem", "fontWeight": "600"}),
        html.Span(" = mixed/ambiguous", style={"color": "#888", "fontSize": "0.75rem"}),
    ], style={"marginBottom": "10px"}),
    dbc.Row([
        dbc.Col([
            dbc.RadioItems(
                id="sent-category-filter",
                options=_SENTIMENT_CATEGORIES,
                value="all",
                inline=True,
                style={"color": "#ffffff", "fontSize": "0.85rem"},
            ),
        ], md=8),
        dbc.Col([
            dbc.Input(id="sent-keyword-filter", placeholder="Filter by keyword…",
                      type="text", size="sm",
                      style={"backgroundColor": "#1a1a1a", "color": "#fff",
                             "border": "1px solid #333"}),
        ], md=4),
    ], className="mb-2"),
    dcc.Loading(
        html.Div(id="sent-news-feed"),
        type="circle", color="#4a90e2",
    ),

    # --- Section 3: Earthquakes ---
    html.Div("Natural Disasters — M≥5.5 Earthquakes (Last 7 Days)", className="section-title mt-4"),
    dcc.Loading(
        html.Div(id="sent-earthquake-table"),
        type="circle", color="#e94560",
    ),

    # --- Section 4: Ticker News ---
    html.Div("Ticker-Specific News", className="section-title mt-4"),
    dbc.Row([
        dbc.Col([
            dbc.InputGroup([
                dbc.Input(id="sent-ticker-input", placeholder="Enter ticker (e.g. AAPL)",
                          type="text", size="sm",
                          style={"backgroundColor": "#1a1a1a", "color": "#fff",
                                 "border": "1px solid #333"}),
                dbc.Button("Search", id="sent-ticker-btn", color="primary", size="sm"),
            ]),
        ], md=4),
    ], className="mb-2"),
    dcc.Loading(html.Div(id="sent-ticker-news"), type="circle", color="#4a90e2"),
])


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

@callback(
    Output("sent-gauges-row",    "children"),
    Output("sent-data-store",    "data"),
    Input("sent-refresh-btn",    "n_clicks"),
    Input("sent-auto-refresh",   "n_intervals"),
    prevent_initial_call=False,
)
def update_sentiment_gauges(_clicks, _intervals):
    import time
    from dash import ctx
    # Fetch fresh data when triggered by the refresh button
    if ctx.triggered_id == "sent-refresh-btn":
        refresh_sentiment()
    data = get_sentiment_latest() or {}

    def _gauge_card(value, label, unit="", colour="#4a90e2", low_good=False):
        val_str = f"{value:.1f}" if value is not None else "—"
        return dbc.Col(
            html.Div(className="kpi-card", children=[
                html.Div(val_str, className="kpi-value",
                         style={"fontSize": "1.8rem", "color": colour}),
                html.Div(label, className="kpi-label"),
                html.Div(unit, style={"fontSize": "0.68rem", "color": "#888"}),
            ]),
            xs=6, sm=4, md=3,
        )

    fg = data.get("fear_greed_score")
    fg_colour = "#e94560" if fg is not None and fg < 30 else (
        "#2ecc71" if fg is not None and fg > 70 else "#f0c040"
    )
    fg_label = ("Extreme Fear" if fg is not None and fg < 20 else
                "Fear" if fg is not None and fg < 40 else
                "Neutral" if fg is not None and fg < 60 else
                "Greed" if fg is not None and fg < 80 else "Extreme Greed")

    cards = [
        _gauge_card(fg, f"Fear & Greed — {fg_label}", "0=Fear, 100=Greed", fg_colour),
        _gauge_card(data.get("vix_value"), "VIX", "Volatility Index", "#e74c3c"),
        _gauge_card(data.get("vix_percentile"), "VIX Percentile", "vs 1-year history", "#9b59b6"),
        _gauge_card(data.get("put_call_ratio"), "Put/Call Ratio", "equity options", "#3498db"),
    ]
    return cards, {"ts": time.time()}


@callback(
    Output("sent-news-feed", "children"),
    Input("sent-category-filter", "value"),
    Input("sent-keyword-filter",  "value"),
    Input("sent-data-store",      "data"),
)
def update_news_feed(category, keyword, _store):
    cat = None if category == "all" else category
    articles = get_news(category=cat, hours=48, limit=60) or []

    if keyword:
        kw = keyword.lower()
        articles = [a for a in articles if kw in a.get("headline", "").lower()]

    if not articles:
        return html.Div(
            "No news articles — click Refresh News (requires NEWSAPI_KEY in .env).",
            style={"color": "#888", "fontSize": "0.85rem", "padding": "16px"},
        )

    cards = []
    for art in articles[:40]:
        label = art.get("sentiment_label", "Neutral")
        lc = _LABEL_COLOUR.get(label, "#888")
        pub = art.get("published_at", "")
        if pub:
            pub = str(pub)[:16].replace("T", " ")

        cards.append(
            dbc.Card(
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.A(
                                art.get("headline", ""),
                                href=art.get("url", "#"),
                                target="_blank",
                                style={"color": "#ffffff", "fontWeight": "600",
                                       "fontSize": "0.88rem", "textDecoration": "none"},
                            ),
                        ], md=10),
                        dbc.Col([
                            html.Span(label, style={
                                "fontSize": "0.70rem", "fontWeight": "700",
                                "color": lc, "border": f"1px solid {lc}",
                                "borderRadius": "3px", "padding": "2px 6px",
                                "whiteSpace": "nowrap",
                            }),
                        ], md=2, style={"textAlign": "right"}),
                    ]),
                    html.Div([
                        html.Span(art.get("source", ""), style={"color": "#4a90e2",
                                  "fontSize": "0.72rem", "marginRight": "10px"}),
                        html.Span(pub, style={"color": "#888", "fontSize": "0.72rem"}),
                        html.Span(f"  [{art.get('category', '')}]",
                                  style={"color": "#555", "fontSize": "0.68rem",
                                         "marginLeft": "6px"}),
                    ], style={"marginTop": "4px"}),
                ], style={"padding": "10px 14px"}),
                style={"backgroundColor": "#1a1a1a", "border": "1px solid #2a2a2a",
                       "borderRadius": "4px", "marginBottom": "6px"},
            )
        )
    return html.Div(cards)


@callback(
    Output("sent-earthquake-table", "children"),
    Input("sent-data-store", "data"),
    Input("sent-quake-refresh-btn", "n_clicks"),
)
def update_earthquake_table(_store, _clicks):
    from dash import ctx
    if ctx.triggered_id == "sent-quake-refresh-btn":
        refresh_earthquakes()
    quakes = get_earthquakes(days=7, min_magnitude=5.5) or []

    if not quakes:
        return html.Div("No M≥5.5 earthquakes in the past 7 days.",
                        style={"color": "#888", "fontSize": "0.85rem", "padding": "12px"})

    rows = []
    for q in quakes:
        mag = q.get("magnitude", 0)
        mag_colour = "#e94560" if mag >= 7.0 else ("#f0c040" if mag >= 6.0 else "#aaa")
        zone_badge = (
            html.Span("⚠ Econ Zone", style={
                "fontSize": "0.68rem", "color": "#f0c040",
                "border": "1px solid #f0c040", "borderRadius": "3px", "padding": "1px 4px",
                "marginLeft": "6px",
            }) if q.get("economic_zone_flag") else None
        )
        rows.append(html.Tr([
            html.Td(html.Span(f"M{mag:.1f}",
                              style={"color": mag_colour, "fontWeight": "700"})),
            html.Td([q.get("location", ""), zone_badge],
                    style={"color": "#fff", "paddingLeft": "12px"}),
            html.Td(f"{q.get('depth_km', 0):.0f} km",
                    style={"color": "#888", "paddingLeft": "12px"}),
            html.Td(str(q.get("event_time", ""))[:16].replace("T", " "),
                    style={"color": "#888", "paddingLeft": "12px", "fontSize": "0.78rem"}),
        ]))

    return dbc.Table(
        [
            html.Thead(html.Tr([
                html.Th("Mag", style={"color": "#888", "fontWeight": "400", "fontSize": "0.78rem"}),
                html.Th("Location", style={"color": "#888", "fontWeight": "400", "fontSize": "0.78rem"}),
                html.Th("Depth", style={"color": "#888", "fontWeight": "400", "fontSize": "0.78rem"}),
                html.Th("Time (UTC)", style={"color": "#888", "fontWeight": "400", "fontSize": "0.78rem"}),
            ])),
            html.Tbody(rows),
        ],
        bordered=False, hover=True, size="sm",
        style={"backgroundColor": "#111111"},
    )


@callback(
    Output("sent-ticker-news", "children"),
    Input("sent-ticker-btn",  "n_clicks"),
    State("sent-ticker-input", "value"),
    prevent_initial_call=True,
)
def update_ticker_news(_clicks, ticker):
    if not ticker:
        return html.Div("Enter a ticker above.", style={"color": "#888", "fontSize": "0.85rem"})
    articles = get_news_for_ticker(ticker.strip().upper(), hours=72) or []
    if not articles:
        return html.Div(f"No recent news found for {ticker.upper()}.",
                        style={"color": "#888", "fontSize": "0.85rem"})

    cards = []
    for art in articles[:15]:
        label  = art.get("sentiment_label", "Neutral")
        lc     = _LABEL_COLOUR.get(label, "#888")
        pub    = str(art.get("published_at", ""))[:16].replace("T", " ")
        cards.append(html.Div([
            html.A(art.get("headline", ""), href=art.get("url", "#"), target="_blank",
                   style={"color": "#fff", "fontSize": "0.86rem", "textDecoration": "none"}),
            html.Span(f"  {label}", style={"color": lc, "fontSize": "0.72rem",
                                           "marginLeft": "8px", "fontWeight": "600"}),
            html.Div(f"{art.get('source', '')}  ·  {pub}",
                     style={"color": "#888", "fontSize": "0.70rem", "marginTop": "2px"}),
        ], style={"padding": "8px 0", "borderBottom": "1px solid #1e1e1e"}))
    return html.Div(cards)


@callback(
    Output("sent-refresh-status", "children"),
    Input("sent-news-refresh-btn",   "n_clicks"),
    prevent_initial_call=True,
)
def trigger_news_refresh(_):
    res = refresh_news() or {}
    return f"News refresh: {res.get('articles_upserted', 0)} new articles."
