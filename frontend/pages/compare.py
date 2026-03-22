"""
frontend.pages.compare
======================
Page 4 – Batch Compare.

Allows comparing up to 50 tickers side-by-side on:
- Gross Margin, ROIC, FCF Margin, Interest Coverage, P/E.
- Colour-coded heatmap (green / neutral / red).
- Overall quality score (0–100).
- Zombie flag.
- Excel export.
"""

from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, dcc, html

from frontend.api_client import compare_tickers
from frontend.config import API_BASE_URL

dash.register_page(__name__, path="/compare", name="Batch Compare", title="Batch Compare")

_BAND_COLOURS = {
    "good":    "#1a5c38",
    "bad":     "#5c1a1a",
    "neutral": "#1a1a1a",
    "na":      "#0d0d0d",
}

_METRICS = [
    ("gross_margin",      "Gross Margin",       lambda v: f"{v:.1f}%" if v is not None else "—"),
    ("roic",              "ROIC",               lambda v: f"{v*100:.1f}%" if v is not None else "—"),
    ("fcf_margin",        "FCF Margin",         lambda v: f"{v:.1f}%" if v is not None else "—"),
    ("interest_coverage", "Int. Coverage",      lambda v: f"{v:.2f}x" if v is not None else "—"),
    ("pe_ratio",          "P/E",                lambda v: f"{v:.1f}" if v is not None else "—"),
]


def _build_compare_table(rows: list[dict]) -> html.Div:
    if not rows:
        return html.P("No results.", style={"color": "#ffffff"})

    _th = {"color": "#ffffff", "fontWeight": "600", "whiteSpace": "normal",
            "wordBreak": "break-word", "padding": "8px 6px"}

    # Header row
    header = [
        html.Th("Ticker",  style={**_th, "width": "90px"}),
        html.Th("Company", style={**_th, "width": "150px"}),
    ] + [
        html.Th(label, style={**_th, "textAlign": "center", "width": "110px"})
        for _, label, _ in _METRICS
    ] + [
        html.Th("Score",  style={**_th, "textAlign": "center", "width": "70px"}),
        html.Th("Zombie", style={**_th, "textAlign": "center", "width": "70px"}),
    ]

    table_rows = []
    for r in rows:
        cells = [
            html.Td(r["ticker"], style={"fontWeight": "800", "color": "#e94560",
                                        "whiteSpace": "normal", "wordBreak": "break-word"}),
            html.Td(r.get("name", ""), style={"color": "#ffffff", "fontSize": "0.82rem",
                                               "whiteSpace": "normal", "wordBreak": "break-word"}),
        ]
        for field, _, fmt in _METRICS:
            cell_data = r.get(field, {})
            val = cell_data.get("value") if isinstance(cell_data, dict) else None
            band = cell_data.get("band", "neutral") if isinstance(cell_data, dict) else "neutral"
            bg = _BAND_COLOURS.get(band, "#1a1a1a")
            cells.append(
                html.Td(
                    fmt(val),
                    style={
                        "textAlign": "center",
                        "backgroundColor": bg,
                        "fontWeight": "600",
                        "fontStyle": "italic" if band == "bad" else "normal",
                        "color": "#2ecc71" if band == "good" else
                                 "#e67e22" if band == "bad" else "#ffffff",
                        "padding": "8px 4px",
                        "borderBottom": "1px solid #2a2a2a",
                        "whiteSpace": "normal",
                        "wordBreak": "break-word",
                    },
                )
            )

        score = r.get("overall_score")
        score_col = "#2ecc71" if (score or 0) >= 80 else "#f39c12" if (score or 0) >= 50 else "#e67e22"
        cells.append(html.Td(
            f"{score:.0f}" if score is not None else "—",
            style={"textAlign": "center", "fontWeight": "800", "color": score_col},
        ))
        cells.append(html.Td(
            html.Span("ZOMBIE", className="zombie-badge") if r.get("is_zombie") else "—",
            style={"textAlign": "center"},
        ))

        table_rows.append(html.Tr(cells, style={"borderBottom": "1px solid #2a2a2a"}))

    return html.Div(
        html.Table(
            [html.Thead(html.Tr(header)), html.Tbody(table_rows)],
            style={"width": "100%", "borderCollapse": "collapse", "fontSize": "0.85rem"},
        ),
        style={"overflowX": "auto"},
    )


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

layout = html.Div([
    html.Div([
        html.Span("Batch ", className="page-title"),
        html.Span("Compare", className="page-title title-accent"),
    ], style={"marginBottom": "20px"}),

    dbc.Row([
        dbc.Col([
            dbc.InputGroup([
                dbc.Input(
                    id="compare-ticker-input",
                    placeholder="Enter tickers separated by commas: AAPL, MSFT, GOOGL …",
                    style={"backgroundColor": "#111111", "color": "#ffffff",
                           "border": "1px solid #2a2a2a"},
                ),
                dbc.Button("Analyze", id="compare-analyze-btn", color="primary"),
            ]),
            html.Small("Up to 50 tickers. Press Analyze to compare.",
                       style={"color": "#ffffff", "marginTop": "4px", "display": "block"}),
        ], md=9),
        dbc.Col([
            html.A(
                dbc.Button([html.I(className="bi-file-earmark-excel me-2"), "Export Excel"],
                           id="compare-export-btn", color="success", size="sm",
                           outline=True, disabled=True),
                id="compare-export-link",
                target="_blank",
            ),
        ], md=3, style={"textAlign": "right", "paddingTop": "4px"}),
    ], className="mb-4"),

    dcc.Loading(
        html.Div(id="compare-results"),
        type="circle",
        color="#4a90e2",
    ),

    dcc.Store(id="compare-tickers-store"),
])


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

@callback(
    Output("compare-results",       "children"),
    Output("compare-tickers-store", "data"),
    Input("compare-analyze-btn", "n_clicks"),
    State("compare-ticker-input",   "value"),
    prevent_initial_call=True,
)
def run_compare(n_clicks, ticker_str):
    if not ticker_str:
        return dbc.Alert("Enter at least one ticker symbol.", color="warning"), []

    tickers = [t.strip().upper() for t in ticker_str.replace(",", " ").split() if t.strip()][:50]
    result = compare_tickers(tickers)

    if not result:
        return dbc.Alert("API unavailable or no data found.", color="danger"), []

    rows = result.get("rows", [])
    if not rows:
        return html.P("No data found for the provided tickers. "
                      "Fetch their statements first via the Screener page.",
                      style={"color": "#ffffff"}), []

    table = _build_compare_table(rows)
    _badge = lambda text, bg, fg: html.Span(text, style={
        "backgroundColor": bg, "color": fg,
        "padding": "2px 8px", "borderRadius": "3px",
        "marginRight": "6px", "fontSize": "0.78rem", "fontWeight": "600",
    })
    _threshold_rows = [
        ("Gross Margin",    "≥ 40%",  "15–40%",  "< 15%"),
        ("ROIC",            "≥ 12%",  "5–12%",   "< 5%"),
        ("FCF Margin",      "≥ 10%",  "0–10%",   "< 0%"),
        ("Int. Coverage",   "≥ 3×",   "1–3×",    "< 1×"),
        ("P/E",             "≤ 15",   "15–40",   "> 40"),
    ]
    legend = html.Div([
        html.Div([
            html.Span("Colour key: ", style={"color": "#aaaaaa", "marginRight": "8px",
                                              "fontSize": "0.78rem"}),
            _badge("Good",    "#1a5c38", "#2ecc71"),
            _badge("Neutral", "#1a1a1a", "#ffffff"),
            _badge("Bad",     "#5c1a1a", "#e67e22"),
        ], style={"marginBottom": "8px"}),
        html.Details([
            html.Summary("Threshold reference", style={
                "color": "#aaaaaa", "fontSize": "0.75rem", "cursor": "pointer",
                "userSelect": "none", "marginBottom": "6px",
            }),
            html.Table([
                html.Thead(html.Tr([
                    html.Th("Metric",  style={"color": "#888", "fontWeight": 600,
                                              "fontSize": "0.72rem", "padding": "3px 10px 3px 0"}),
                    html.Th(_badge("Good",    "#1a5c38", "#2ecc71"),
                            style={"fontSize": "0.72rem", "padding": "3px 10px 3px 0"}),
                    html.Th(_badge("Neutral", "#1a1a1a", "#ffffff"),
                            style={"fontSize": "0.72rem", "padding": "3px 10px 3px 0"}),
                    html.Th(_badge("Bad",     "#5c1a1a", "#e67e22"),
                            style={"fontSize": "0.72rem", "padding": "3px 0 3px 0"}),
                ])),
                html.Tbody([
                    html.Tr([
                        html.Td(metric, style={"color": "#cccccc", "fontSize": "0.72rem",
                                               "padding": "2px 10px 2px 0"}),
                        html.Td(good,   style={"color": "#2ecc71", "fontSize": "0.72rem",
                                               "padding": "2px 10px 2px 0"}),
                        html.Td(neutral, style={"color": "#ffffff", "fontSize": "0.72rem",
                                                "padding": "2px 10px 2px 0"}),
                        html.Td(bad,    style={"color": "#e67e22", "fontSize": "0.72rem",
                                               "padding": "2px 0 2px 0"}),
                    ])
                    for metric, good, neutral, bad in _threshold_rows
                ]),
            ], style={"borderCollapse": "collapse"}),
        ], style={"marginTop": "2px"}),
    ], style={"marginBottom": "12px"})

    return html.Div([legend, table]), tickers


@callback(
    Output("compare-export-btn",  "disabled"),
    Output("compare-export-link", "href"),
    Input("compare-tickers-store", "data"),
)
def update_export_link(tickers):
    if not tickers:
        return True, "#"
    # POST export is done via a form; provide a helper note
    return False, f"{API_BASE_URL}/compare/export.xlsx"
