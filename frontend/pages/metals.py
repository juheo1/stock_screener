"""
frontend.pages.metals
=====================
Page 6 – Metals Intelligence.

Displays:
- Current spot price cards for gold, silver, platinum, palladium, copper.
- Gold/silver ratio with description.
- Historical price chart (selectable metal and timeframe, up to 10Y).
- COMEX vault inventory (GLD/SLV ETF holdings proxy) with trend charts.
- Personal stack tracker (add transactions, view current valuation).
"""

from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from dash import ALL, Input, Output, State, callback, dcc, html

from frontend.api_client import (
    add_stack_transaction,
    admin_refresh_comex,
    delete_stack_transaction,
    get_metal_history,
    get_metal_inventory_history,
    get_metal_stack,
    get_metals,
)

dash.register_page(__name__, path="/metals", name="Metals Intel", title="Metals Intel")

_METAL_META = {
    "gold":      {"label": "Gold",      "unit": "USD/troy oz", "colour": "#f0c040"},
    "silver":    {"label": "Silver",    "unit": "USD/troy oz", "colour": "#c0c0c0"},
    "platinum":  {"label": "Platinum",  "unit": "USD/troy oz", "colour": "#e5e4e2"},
    "palladium": {"label": "Palladium", "unit": "USD/troy oz", "colour": "#cec2aa"},
    "copper":    {"label": "Copper",    "unit": "USD/lb",      "colour": "#b87333"},
}

_METAL_DESCRIPTIONS = {
    "gold":      "Safe-haven monetary metal. Inversely correlated with real interest rates and the USD. Central banks hold gold as reserve asset. Key driver: real yields, USD strength, geopolitical risk.",
    "silver":    "Dual-role metal — monetary store of value AND industrial input (solar panels, EVs, electronics). More volatile than gold. Tends to outperform gold in bull markets.",
    "platinum":  "Industrial precious metal — primary use in catalytic converters (ICE vehicles). Also used in hydrogen fuel cells. Historically expensive vs gold; now usually at a discount.",
    "palladium": "Almost entirely consumed by autocatalytic converters for gasoline engines. Supply dominated by Russia and South Africa. Highly sensitive to auto production volumes.",
    "copper":    "The industrial bellwether ('Dr. Copper'). Widely used in construction, electrical wiring, EVs, and electronics. Rising copper prices historically signal global economic expansion.",
}

_GS_RATIO_DESCRIPTION = (
    "Gold/Silver Ratio — how many oz of silver it takes to buy 1 oz of gold. "
    "Historical average ~65–70×. A high ratio (>80) signals silver is cheap relative to gold "
    "and often precedes silver outperformance. A low ratio (<50) favours selling silver for gold."
)

_INVENTORY_DESCRIPTION = (
    "COMEX vault inventory estimated from GLD (SPDR Gold Trust) and SLV (iShares Silver Trust) "
    "ETF holdings. GLD and SLV hold physical metal in COMEX-approved vaults and represent the "
    "largest component of COMEX registered/eligible inventory. "
    "Declining inventory signals rising physical demand or metal drain from exchanges. "
    "Data source: ETF shares outstanding × (ETF price ÷ spot price)."
)


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

layout = html.Div([
    html.Div([
        html.Span("Metals ", className="page-title"),
        html.Span("Intelligence", className="page-title title-accent"),
    ], style={"marginBottom": "20px"}),

    dcc.Loading([
        # Spot price cards
        html.Div("Current Spot Prices", className="section-title"),
        html.P(
            "Daily closing prices from COMEX/NYMEX futures contracts via yfinance. "
            "Gold, silver, platinum, and palladium are priced per troy oz; copper per lb.",
            style={"fontSize": "0.80rem", "color": "#888888", "marginBottom": "12px",
                   "marginTop": "-4px"},
        ),
        dbc.Row(id="metals-price-row", className="g-3 mb-2"),

        # Metal descriptions
        dbc.Row([
            dbc.Col(
                dbc.Card([
                    dbc.CardBody([
                        html.Div(meta["label"],
                                 style={"fontWeight": "700", "color": meta["colour"],
                                        "fontSize": "0.85rem", "marginBottom": "4px"}),
                        html.P(_METAL_DESCRIPTIONS[k],
                               style={"fontSize": "0.78rem", "color": "#888888", "margin": 0}),
                    ], style={"padding": "10px 14px"}),
                ], style={"backgroundColor": "#1a1a1a", "border": "1px solid #2a2a2a",
                          "borderRadius": "6px"}),
                xs=12, sm=6, md=4, lg=4,
                className="mb-2",
            )
            for k, meta in _METAL_META.items()
        ], className="g-2 mb-4"),

        # Gold/silver ratio + price chart
        dbc.Row([
            dbc.Col([
                html.Div(id="metals-gs-ratio", className="kpi-card text-center",
                         style={"padding": "20px"}),
                html.P(
                    _GS_RATIO_DESCRIPTION,
                    style={"fontSize": "0.75rem", "color": "#888888", "marginTop": "10px",
                           "lineHeight": "1.5"},
                ),
            ], md=3),
            dbc.Col([
                # Chart controls
                dbc.Row([
                    dbc.Col([
                        dcc.Dropdown(
                            id="metals-chart-metal",
                            options=[{"label": m["label"], "value": k}
                                     for k, m in _METAL_META.items()],
                            value="gold",
                            clearable=False,
                            style={"backgroundColor": "#111111", "color": "#000"},
                        ),
                    ], md=5),
                    dbc.Col([
                        dbc.RadioItems(
                            id="metals-chart-days",
                            options=[
                                {"label": "1Y",  "value": 365},
                                {"label": "2Y",  "value": 730},
                                {"label": "5Y",  "value": 1825},
                                {"label": "10Y", "value": 3650},
                            ],
                            value=365,
                            inline=True,
                            style={"paddingTop": "8px", "color": "#ffffff"},
                        ),
                    ], md=7),
                ], className="mb-2"),
                html.Div(className="chart-container", children=[
                    dcc.Loading(dcc.Graph(id="metals-chart", config={"displayModeBar": False})),
                ]),
            ], md=9),
        ], className="g-3 mb-4"),

    ], type="circle", color="#f0c040"),

    # ---------------------------------------------------------------------------
    # COMEX Inventory Section
    # ---------------------------------------------------------------------------
    html.Hr(style={"borderColor": "#2a2a2a"}),
    html.Div([
        html.Span("COMEX Vault ", className="section-title"),
        html.Span("Inventory", className="section-title", style={"color": "#f0c040"}),
    ]),
    html.P(
        _INVENTORY_DESCRIPTION,
        style={"fontSize": "0.80rem", "color": "#888888", "marginBottom": "12px"},
    ),

    dbc.Row([
        dbc.Col([
            dbc.RadioItems(
                id="comex-chart-days",
                options=[
                    {"label": "1Y",  "value": 365},
                    {"label": "2Y",  "value": 730},
                    {"label": "5Y",  "value": 1825},
                    {"label": "10Y", "value": 3650},
                ],
                value=1825,
                inline=True,
                style={"color": "#ffffff"},
            ),
        ], md=8),
        dbc.Col([
            dbc.Button(
                [html.I(className="bi-arrow-clockwise me-2"), "Refresh COMEX Data"],
                id="comex-refresh-btn",
                color="warning",
                size="sm",
                outline=True,
                style={"float": "right"},
                title="Fetch GLD/SLV ETF holdings history — takes ~30–60 s",
            ),
        ], md=4),
    ], className="mb-2"),

    dcc.Loading(
        html.Div(id="comex-refresh-status",
                 style={"fontSize": "0.82rem", "color": "#2ecc71", "marginBottom": "8px"}),
        type="dot",
    ),

    dcc.Loading(
        dbc.Row(id="comex-inventory-row", className="g-3"),
        type="circle",
        color="#f0c040",
    ),

    # ---------------------------------------------------------------------------
    # Stack tracker
    # ---------------------------------------------------------------------------
    html.Hr(style={"borderColor": "#2a2a2a"}),
    html.Div("Personal Stack Tracker", className="section-title"),

    dbc.Row([
        dbc.Col([
            html.Div("Metal", className="threshold-label"),
            dcc.Dropdown(
                id="stack-metal",
                options=[{"label": m["label"], "value": k}
                         for k, m in _METAL_META.items()],
                value="gold",
                clearable=False,
                style={"backgroundColor": "#111111"},
            ),
        ], md=2),
        dbc.Col([
            html.Div("Troy Oz", className="threshold-label"),
            dbc.Input(id="stack-oz", type="number", placeholder="e.g. 1.0", min=0.001,
                      style={"backgroundColor": "#111111", "color": "#e0e0e0",
                             "border": "1px solid #2a2a2a"}),
        ], md=2),
        dbc.Col([
            html.Div("Price Paid ($/oz)", className="threshold-label"),
            dbc.Input(id="stack-price", type="number", placeholder="e.g. 1900",
                      style={"backgroundColor": "#111111", "color": "#e0e0e0",
                             "border": "1px solid #2a2a2a"}),
        ], md=2),
        dbc.Col([
            html.Div("Date", className="threshold-label"),
            dbc.Input(id="stack-date", type="date",
                      style={"backgroundColor": "#111111", "color": "#e0e0e0",
                             "border": "1px solid #2a2a2a"}),
        ], md=2),
        dbc.Col([
            html.Div("\u00a0", className="threshold-label"),
            dbc.Button("Add Transaction", id="stack-add-btn", color="warning", size="sm"),
        ], md=2),
        dbc.Col([
            html.Div(id="stack-status", style={"paddingTop": "28px", "fontSize": "0.82rem",
                                                "color": "#2ecc71"}),
        ], md=2),
    ], className="mb-3"),

    dcc.Loading(html.Div(id="stack-summary"), type="dot", color="#f0c040"),

    html.Div(id="stack-remove-status",
             style={"marginTop": "6px", "fontSize": "0.82rem", "color": "#e74c3c"}),
])


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

@callback(
    Output("metals-price-row", "children"),
    Output("metals-gs-ratio",  "children"),
    Input("metals-price-row",  "id"),  # trigger on page load
)
def load_metal_prices(_):
    data = get_metals()
    if not data:
        return [dbc.Alert("API unavailable.", color="danger")], "—"

    prices = data.get("current_prices", {})
    gs_ratio = data.get("gold_silver_ratio")

    cards = []
    for metal_id, meta in _METAL_META.items():
        p = prices.get(metal_id, {})
        price = p.get("price")
        obs = p.get("date", "")
        cards.append(dbc.Col(
            html.Div(className="metal-card", children=[
                html.Div(meta["label"], className="metal-name"),
                html.Div(
                    f"${price:,.2f}" if price else "—",
                    className="metal-price",
                    style={"color": meta["colour"]},
                ),
                html.Div(meta["unit"], className="metal-unit"),
                html.Div(str(obs), style={"fontSize": "0.70rem", "color": "#ffffff",
                                           "marginTop": "4px"}),
            ]),
            xs=6, sm=4, md=2,
        ))

    gs_el = html.Div([
        html.Div("Gold / Silver Ratio", className="kpi-label"),
        html.Div(
            f"{gs_ratio:.1f}x" if gs_ratio else "—",
            className="kpi-value",
            style={"color": "#f0c040", "fontSize": "2.2rem"},
        ),
        html.Small("Historical avg ~65–70x", style={"color": "#ffffff", "fontSize": "0.72rem"}),
    ])

    return cards, gs_el


@callback(
    Output("metals-chart", "figure"),
    Input("metals-chart-metal", "value"),
    Input("metals-chart-days",  "value"),
)
def update_metals_chart(metal_id, days):
    meta = _METAL_META.get(metal_id, {})
    colour = meta.get("colour", "#aaa")
    label = meta.get("label", metal_id)

    history = get_metal_history(metal_id, days=days)

    fig = go.Figure()
    if history:
        dates  = [h["date"] for h in history]
        prices = [h["price"] for h in history]
        fig.add_trace(go.Scatter(
            x=dates, y=prices,
            mode="lines",
            line=dict(color=colour, width=2),
            fill="tozeroy",
            fillcolor=colour,
            opacity=0.08 if len(prices) > 1 else 1,
            name=label,
        ))
    else:
        fig.add_annotation(
            text="No data — fetch metals prices first",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(color="#ffffff", size=14),
        )

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#111111",
        plot_bgcolor="#111111",
        font=dict(color="#ffffff"),
        margin=dict(l=60, r=10, t=10, b=50),
        xaxis=dict(gridcolor="#2a2a2a", color="#ffffff"),
        yaxis=dict(title=f"{label} ({meta.get('unit', '')})",
                   gridcolor="#2a2a2a", tickformat="$,.2f", color="#ffffff"),
        showlegend=False,
        height=300,
    )
    return fig


@callback(
    Output("comex-inventory-row",  "children"),
    Input("comex-chart-days",      "value"),
    Input("comex-refresh-btn",     "n_clicks"),
)
def update_comex_inventory(days, _n_clicks):
    charts = []
    for metal_id, colour, etf_sym in [
        ("gold",   "#f0c040", "GLD"),
        ("silver", "#c0c0c0", "SLV"),
    ]:
        history = get_metal_inventory_history(metal_id, days=days) or []

        fig = go.Figure()
        if history:
            dates = [h["date"] for h in history]
            ozs   = [h["inventory_oz"] / 1_000_000 for h in history]  # millions of oz

            fig.add_trace(go.Scatter(
                x=dates, y=ozs,
                mode="lines",
                line=dict(color=colour, width=2),
                fill="tozeroy",
                fillcolor=colour,
                opacity=0.12,
                name=f"{metal_id.capitalize()} ({etf_sym})",
            ))

            # Annotate latest value
            if ozs:
                fig.add_annotation(
                    x=dates[-1], y=ozs[-1],
                    text=f"{ozs[-1]:.1f}M oz",
                    showarrow=False,
                    font=dict(color=colour, size=11),
                    xanchor="right",
                    yanchor="bottom",
                )
        else:
            fig.add_annotation(
                text=f"No {etf_sym} inventory data — click Refresh COMEX Data",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False,
                font=dict(color="#888888", size=12),
            )

        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#111111",
            plot_bgcolor="#111111",
            font=dict(color="#ffffff"),
            title=dict(
                text=f"{metal_id.capitalize()} — {etf_sym} Vault Holdings",
                font=dict(color=colour, size=12),
            ),
            margin=dict(l=60, r=10, t=35, b=40),
            xaxis=dict(gridcolor="#2a2a2a", color="#ffffff"),
            yaxis=dict(title="Million Troy Oz", gridcolor="#2a2a2a",
                       tickformat=",.1f", color="#ffffff"),
            showlegend=False,
            height=260,
        )

        charts.append(dbc.Col(
            html.Div(className="chart-container", children=[
                dcc.Graph(figure=fig, config={"displayModeBar": False}),
            ]),
            md=6,
        ))

    return charts


@callback(
    Output("comex-refresh-status", "children"),
    Input("comex-refresh-btn",     "n_clicks"),
    prevent_initial_call=True,
)
def refresh_comex(_n_clicks):
    res = admin_refresh_comex()
    if not res:
        return "Refresh failed — check server logs."
    total = sum(res.get("results", {}).values())
    return f"COMEX inventory refreshed — {total:,} rows stored."


def _render_stack_summary():
    """Build the stack summary + transactions display from current API data."""
    stack = get_metal_stack()
    if not stack:
        return html.P("No stack data.", style={"color": "#ffffff"})

    transactions = stack.get("transactions", [])
    totals = stack.get("totals", {})
    total_value = stack.get("portfolio_value_usd", 0)

    if not totals:
        return html.P("No transactions yet. Add your first transaction above.",
                      style={"color": "#ffffff"})

    summary_rows = []
    for metal_id, agg in totals.items():
        meta = _METAL_META.get(metal_id, {})
        colour = meta.get("colour", "#aaa")
        pnl = agg.get("unrealised_pnl")
        pnl_str = f"${pnl:+,.2f}" if pnl is not None else "—"
        pnl_col = "#2ecc71" if (pnl or 0) >= 0 else "#e74c3c"
        summary_rows.append(html.Tr([
            html.Td(meta.get("label", metal_id), style={"color": colour, "fontWeight": "600"}),
            html.Td(f"{agg['oz']:.3f} oz"),
            html.Td(f"${agg['cost_basis']:,.2f}", style={"color": "#ffffff"}),
            html.Td(f"${agg['current_value']:,.2f}" if agg.get("current_value") else "—"),
            html.Td(pnl_str, style={"color": pnl_col, "fontWeight": "600"}),
        ]))

    tx_rows = []
    for i, tx in enumerate(transactions, start=1):
        metal_id = tx.get("metal", "")
        meta = _METAL_META.get(metal_id, {})
        colour = meta.get("colour", "#aaa")
        tx_rows.append(html.Tr([
            html.Td(f"#{i}", style={"color": "#888888", "fontSize": "0.78rem"}),
            html.Td(meta.get("label", metal_id), style={"color": colour}),
            html.Td(f"{tx.get('oz', 0):.3f} oz"),
            html.Td(f"${tx.get('price_per_oz', 0):,.2f}/oz"),
            html.Td(tx.get("date", "—"), style={"color": "#888888"}),
            html.Td(tx.get("note", "") or "—", style={"color": "#888888", "fontSize": "0.78rem"}),
            html.Td(
                dbc.Button(
                    "✕",
                    id={"type": "tx-delete-btn", "index": i - 1},  # 0-based
                    color="danger",
                    size="sm",
                    outline=True,
                    style={"padding": "1px 7px", "fontSize": "0.72rem", "lineHeight": "1.4"},
                ),
            ),
        ]))

    return html.Div([
        dbc.Table(
            [
                html.Thead(html.Tr([
                    html.Th("Metal"), html.Th("Oz"), html.Th("Cost Basis"),
                    html.Th("Current Value"), html.Th("Unrealised P&L"),
                ])),
                html.Tbody(summary_rows),
                html.Tfoot(html.Tr([
                    html.Td("Total", colSpan=3, style={"fontWeight": "800"}),
                    html.Td(f"${total_value:,.2f}",
                            style={"fontWeight": "800", "color": "#f0c040"}),
                    html.Td(""),
                ])),
            ],
            bordered=False, hover=True, size="sm",
            style={"backgroundColor": "#111111"},
        ),
        (html.Div([
            html.Div("Individual Transactions", style={
                "fontSize": "0.78rem", "fontWeight": 700, "color": "#666666",
                "textTransform": "uppercase", "letterSpacing": "0.07em",
                "marginTop": "14px", "marginBottom": "4px",
            }),
            dbc.Table(
                [
                    html.Thead(html.Tr([
                        html.Th("#"), html.Th("Metal"), html.Th("Oz"),
                        html.Th("Price Paid"), html.Th("Date"), html.Th("Note"),
                        html.Th(""),
                    ])),
                    html.Tbody(tx_rows),
                ],
                bordered=False, size="sm",
                style={"backgroundColor": "#111111", "fontSize": "0.82rem"},
            ),
        ]) if tx_rows else html.Div()),
    ])


@callback(
    Output("stack-status",  "children"),
    Output("stack-summary", "children"),
    Input("stack-add-btn",  "n_clicks"),
    State("stack-metal",    "value"),
    State("stack-oz",       "value"),
    State("stack-price",    "value"),
    State("stack-date",     "value"),
    prevent_initial_call=False,
)
def handle_stack(n_clicks, metal, oz, price, tx_date):
    if n_clicks and all([metal, oz, price, tx_date]):
        res = add_stack_transaction(metal, oz, price, tx_date)
        status = "Transaction added." if res else "Error adding transaction."
    else:
        status = ""
    return status, _render_stack_summary()


@callback(
    Output("stack-remove-status", "children"),
    Output("stack-summary", "children", allow_duplicate=True),
    Input({"type": "tx-delete-btn", "index": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def remove_stack_tx(n_clicks_list):
    triggered = dash.ctx.triggered_id
    if not triggered or not isinstance(triggered, dict):
        return "", dash.no_update
    if not any(n for n in (n_clicks_list or []) if n):
        return "", dash.no_update
    idx = triggered["index"]  # 0-based transaction index
    res = delete_stack_transaction(idx)
    if res:
        return "Transaction removed.", _render_stack_summary()
    return "Remove failed — invalid transaction?", dash.no_update
