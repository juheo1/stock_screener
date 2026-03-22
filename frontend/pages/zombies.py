"""
frontend.pages.zombies
======================
Page 3 – Zombie Kill List.

Displays all tickers flagged as zombie companies with:
- Severity score and colour-coded bar.
- Reasons (negative FCF, coverage < 1, margin deterioration).
- Metric snapshot.
- Search and sector filter.
- CSV export.
"""

from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, callback, dcc, html

from frontend.api_client import get_zombies
from frontend.config import API_BASE_URL

dash.register_page(__name__, path="/zombies", name="Zombie Kill List", title="Zombie Kill List")

# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------

def _zombie_row(z: dict) -> dbc.Card:
    severity = z.get("severity") or 0
    reasons = z.get("reasons") or []
    metrics = {
        "Gross Margin":        (z.get("gross_margin"),     "%"),
        "FCF Margin":          (z.get("fcf_margin"),       "%"),
        "Int. Coverage":       (z.get("interest_coverage"), "x"),
        "P/E":                 (z.get("pe_ratio"),          ""),
        "ROIC":                (z.get("roic"),              ""),
    }

    def _fmt(val, unit):
        if val is None:
            return "—"
        if unit == "%" :
            return f"{val:.1f}%"
        if unit == "x":
            return f"{val:.2f}x"
        return f"{val:.4f}"

    metric_badges = [
        html.Span(
            [html.B(k + ": "), _fmt(v, u)],
            style={"marginRight": "16px", "fontSize": "0.78rem",
                   "color": "#e74c3c" if (k == "FCF Margin" and (v or 0) < 0)
                            or (k == "Int. Coverage" and (v or 99) < 1) else "#ffffff"},
        )
        for k, (v, u) in metrics.items()
    ]

    return dbc.Card(
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    html.Span(z.get("ticker", ""), style={"fontWeight": "800", "fontSize": "1.1rem",
                                                          "color": "#e94560", "marginRight": "10px"}),
                    html.Span(html.B("ZOMBIE"), className="zombie-badge"),
                    html.Div(z.get("name", ""), style={"color": "#ffffff", "fontSize": "0.82rem",
                                                        "wordBreak": "break-word"}),
                ], md=4),
                dbc.Col([
                    html.Div("Severity", className="threshold-label"),
                    html.Div(className="severity-bar-container", children=[
                        html.Div(className="severity-bar", style={"width": f"{severity:.0f}%"}),
                    ]),
                    html.Div([
                        f"{severity:.0f}/100 ",
                        html.Span(
                            "Critical" if severity >= 70 else
                            "High"     if severity >= 40 else
                            "Moderate" if severity >= 20 else "Low",
                            style={
                                "fontSize": "0.68rem", "fontWeight": "700",
                                "color": (
                                    "#e74c3c" if severity >= 70 else
                                    "#e67e22" if severity >= 40 else
                                    "#f39c12"
                                ),
                            },
                        ),
                    ], style={"fontSize": "0.75rem", "color": "#ffffff", "marginTop": "3px"}),
                ], md=2),
                dbc.Col([
                    html.Div(
                        [html.I(className="bi-x-octagon-fill me-1", style={"color": "#e74c3c"}),
                         html.Span(r, style={"fontSize": "0.78rem", "color": "#ffffff",
                                             "wordBreak": "break-word"})]
                        for r in reasons
                    ),
                ], md=6),
            ]),
            html.Hr(style={"borderColor": "#2a2a2a", "margin": "8px 0"}),
            html.Div(metric_badges, style={"display": "flex", "flexWrap": "wrap"}),
        ]),
        style={"backgroundColor": "#111111", "border": "1px solid #3a1a1a",
               "marginBottom": "8px"},
    )


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

layout = html.Div([
    # Title + export
    dbc.Row([
        dbc.Col([
            html.Span("Zombie ", className="page-title"),
            html.Span("Kill List", className="page-title title-accent"),
        ], md=8),
        dbc.Col([
            html.A(
                dbc.Button([html.I(className="bi-download me-2"), "Export CSV"],
                           color="secondary", size="sm", outline=True),
                href=f"{API_BASE_URL}/zombies/export",
                target="_blank",
                style={"float": "right"},
            ),
        ], md=4),
    ], className="mb-3"),

    # Filters
    dbc.Row([
        dbc.Col([
            dbc.InputGroup([
                dbc.InputGroupText(html.I(className="bi-search")),
                dbc.Input(id="zombie-search", placeholder="Search ticker or name…",
                          debounce=True,
                          style={"backgroundColor": "#111111", "color": "#ffffff",
                                 "border": "1px solid #2a2a2a"}),
            ]),
        ], md=5),
        dbc.Col([
            dbc.Input(id="zombie-sector", placeholder="Filter by sector…",
                      debounce=True,
                      style={"backgroundColor": "#111111", "color": "#ffffff",
                             "border": "1px solid #2a2a2a"}),
        ], md=3),
        dbc.Col([
            html.Div(id="zombie-count",
                     style={"paddingTop": "8px", "color": "#ffffff", "fontSize": "0.82rem"}),
        ], md=4),
    ], className="mb-3"),

    # Severity legend
    dbc.Alert(
        [
            html.I(className="bi-info-circle me-2"),
            html.B("Severity Score (0–100): "),
            "Measures how far each zombie metric breaches its danger threshold. "
            "Negative FCF margin, interest coverage < 1.0×, and a 3-year declining gross margin trend "
            "each contribute up to ~33 points based on magnitude. "
            "Higher scores indicate more deeply distressed companies.",
        ],
        color="dark",
        style={"fontSize": "0.78rem", "border": "1px solid #3a1a1a",
               "backgroundColor": "#1a0a0a", "color": "#cccccc"},
        className="mb-3",
    ),

    dcc.Loading(
        html.Div(id="zombie-list"),
        type="circle",
        color="#e94560",
    ),

    # Pagination controls
    dbc.Row([
        dbc.Col([
            dbc.Pagination(id="zombie-pagination", max_value=1, active_page=1,
                           fully_expanded=False, size="sm",
                           style={"marginTop": "12px"}),
        ]),
    ]),

    dcc.Store(id="zombie-page-store", data=1),
])


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

@callback(
    Output("zombie-list",       "children"),
    Output("zombie-count",      "children"),
    Output("zombie-pagination", "max_value"),
    Input("zombie-search",      "value"),
    Input("zombie-sector",      "value"),
    Input("zombie-page-store",  "data"),
)
def update_zombie_list(search, sector, page):
    result = get_zombies(search=search or None, sector=sector or None,
                         page=page or 1, page_size=20)
    if not result:
        return [dbc.Alert("API unavailable.", color="danger")], "—", 1

    rows = result.get("rows", [])
    meta = result.get("meta", {})
    total = meta.get("total", 0)
    total_pages = meta.get("total_pages", 1)

    if not rows:
        return [html.P("No zombie companies found with current filters.",
                        style={"color": "#ffffff"})], "0 zombies", 1

    cards = [_zombie_row(z) for z in rows]
    count_text = f"{total:,} zombie {'company' if total == 1 else 'companies'} flagged"
    return cards, count_text, total_pages


@callback(
    Output("zombie-page-store", "data"),
    Input("zombie-pagination",  "active_page"),
    prevent_initial_call=True,
)
def update_zombie_page(page):
    return page or 1
