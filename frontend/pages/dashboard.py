"""
frontend.pages.dashboard
========================
Page 1 – Intelligence Hub (Dashboard).

Displays:
- Summary KPI cards (screened, zombies, quality count).
- Market index cards (S&P 500, NASDAQ, VIX, DOW).
- Latest FRED macro series values.
- Latest metals spot prices and gold/silver ratio.
- Refresh button to trigger a data update.
"""

from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, callback, dcc, html

from frontend.api_client import get_dashboard, get_liquidity, get_sentiment_latest

dash.register_page(__name__, path="/", name="Intelligence Hub", title="Intelligence Hub")


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------

def _kpi_card(value: str, label: str, change: str | None = None, change_sign: str = "") -> dbc.Col:
    change_el = []
    if change:
        cls = "kpi-change positive" if change_sign == "+" else (
            "kpi-change negative" if change_sign == "-" else "kpi-change"
        )
        change_el = [html.Div(change, className=cls)]

    return dbc.Col(
        html.Div(
            className="kpi-card",
            children=[
                html.Div(value, className="kpi-value"),
                html.Div(label, className="kpi-label"),
                *change_el,
            ],
        ),
        xs=6, md=3,
    )


def _market_card(label: str, value, change_pct) -> dbc.Col:
    val_str = f"{value:,.2f}" if value else "—"
    sign = "+" if (change_pct or 0) >= 0 else ""
    chg_str = f"{sign}{change_pct:.2f}%" if change_pct is not None else ""
    chg_cls = "kpi-change positive" if (change_pct or 0) >= 0 else "kpi-change negative"

    return dbc.Col(
        html.Div(
            className="kpi-card",
            children=[
                html.Div(val_str, className="kpi-value", style={"fontSize": "1.5rem"}),
                html.Div(label, className="kpi-label"),
                html.Div(chg_str, className=chg_cls) if chg_str else None,
            ],
        ),
        xs=6, md=3,
    )


def _metal_card(metal: str, price, obs_date) -> dbc.Col:
    labels = {
        "gold": ("Gold", "XAU/USD", "bi-circle-fill", "#f0c040"),
        "silver": ("Silver", "XAG/USD", "bi-circle-fill", "#c0c0c0"),
        "platinum": ("Platinum", "XPT/USD", "bi-circle-fill", "#e5e4e2"),
        "palladium": ("Palladium", "XPD/USD", "bi-circle-fill", "#cec2aa"),
        "copper": ("Copper", "HG/USD", "bi-circle-fill", "#b87333"),
    }
    name, unit, icon, colour = labels.get(metal, (metal.title(), "", "bi-circle", "#aaa"))
    price_str = f"${price:,.2f}" if price else "—"

    return dbc.Col(
        html.Div(
            className="metal-card",
            children=[
                html.Div(
                    [html.I(className=f"{icon} me-2", style={"color": colour}), name],
                    className="metal-name",
                ),
                html.Div(price_str, className="metal-price", style={"color": colour}),
                html.Div(unit, className="metal-unit"),
            ],
        ),
        xs=6, sm=4, md=2,
    )


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

layout = html.Div([
    # Header row
    dbc.Row([
        dbc.Col([
            html.Div("Intelligence Hub", className="page-title"),
        ], md=8),
        dbc.Col([
            dbc.Button(
                [html.I(className="bi-arrow-clockwise me-2"), "Refresh Data"],
                id="dash-refresh-btn",
                color="primary",
                size="sm",
                style={"float": "right"},
            ),
        ], md=4),
    ], className="mb-3"),

    # Macro Regime Banner
    html.Div(id="dash-regime-banner", className="mb-3"),

    # Loading wrapper
    dcc.Loading(
        id="dash-loading",
        type="circle",
        color="#4a90e2",
        children=[
            # Summary KPIs
            html.Div("Summary", className="section-title"),
            dbc.Row(id="dash-kpi-row", className="g-3 mb-4"),

            # Market cards
            html.Div("Market Indices", className="section-title"),
            dbc.Row(id="dash-market-row", className="g-3 mb-4"),

            # Metals row
            html.Div("Metals Spot Prices", className="section-title"),
            dbc.Row(id="dash-metals-row", className="g-3 mb-4"),

            # Macro + gold/silver ratio
            dbc.Row([
                dbc.Col([
                    html.Div("Macro Indicators", className="section-title"),
                    html.Div(id="dash-macro-table"),
                ], md=8),
                dbc.Col([
                    html.Div("Gold / Silver Ratio", className="section-title"),
                    html.Div(id="dash-gs-ratio", className="kpi-card text-center",
                             style={"padding": "24px"}),
                ], md=4),
            ], className="g-3"),
        ],
    ),

    dcc.Store(id="dash-data-store"),
    dcc.Interval(id="dash-auto-refresh", interval=5 * 60 * 1000, n_intervals=0),  # 5 min
])


# ---------------------------------------------------------------------------
# Regime banner callback
# ---------------------------------------------------------------------------

@callback(
    Output("dash-regime-banner", "children"),
    Input("dash-auto-refresh", "n_intervals"),
    prevent_initial_call=False,
)
def update_regime_banner(_intervals):
    liq = get_liquidity(days=365) or {}
    regime = liq.get("regime", "NEUTRAL")
    data   = liq.get("data", [])

    sent   = get_sentiment_latest() or {}
    vix    = sent.get("vix_value")
    fg     = sent.get("fear_greed_score")
    pcr    = sent.get("put_call_ratio")

    _rc = {"QE": "#2ecc71", "QT": "#e94560", "NEUTRAL": "#f0c040"}
    _rl = {"QE": "QE — Fed Expanding", "QT": "QT — Fed Tightening", "NEUTRAL": "Neutral"}

    rc = _rc.get(regime, "#f0c040")
    rl = _rl.get(regime, regime)

    nl = data[-1]["net_liquidity"] if data else None
    nl_str  = f"Net Liq: ${nl:,.0f}B" if nl is not None else ""
    vix_str = f"VIX: {vix:.1f}" if vix is not None else ""
    fg_str  = f"F&G: {fg:.0f}" if fg is not None else ""
    pcr_str = f"P/C: {pcr:.2f}" if pcr is not None else ""

    ticker_items = [s for s in [nl_str, vix_str, fg_str, pcr_str] if s]

    return html.Div(
        dbc.Row([
            dbc.Col([
                html.Span("FED REGIME  ", style={"fontSize": "0.68rem", "color": "#888",
                                                  "letterSpacing": "0.08em"}),
                html.Span(rl, style={
                    "fontSize": "0.78rem", "fontWeight": "700", "color": rc,
                    "border": f"1px solid {rc}", "borderRadius": "3px",
                    "padding": "2px 8px",
                }),
            ], md=3, style={"display": "flex", "alignItems": "center", "gap": "6px"}),
            dbc.Col([
                html.Div(
                    "  ·  ".join(ticker_items),
                    style={"fontSize": "0.80rem", "color": "#cccccc", "letterSpacing": "0.06em"},
                ),
            ], md=9, style={"display": "flex", "alignItems": "center"}),
        ], className="g-0"),
        style={
            "backgroundColor": "#0d1117",
            "border": f"1px solid {rc}22",
            "borderLeft": f"3px solid {rc}",
            "borderRadius": "4px",
            "padding": "8px 16px",
        },
    )


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

@callback(
    Output("dash-data-store", "data"),
    Input("dash-refresh-btn", "n_clicks"),
    Input("dash-auto-refresh", "n_intervals"),
    prevent_initial_call=False,
)
def load_dashboard_data(_clicks, _intervals):
    """Fetch dashboard data from the API and store it."""
    return get_dashboard()


@callback(
    Output("dash-kpi-row", "children"),
    Input("dash-data-store", "data"),
)
def update_kpi_row(data):
    if not data:
        return [dbc.Col(dbc.Alert("API unavailable — start the backend server.", color="danger"))]
    return [
        _kpi_card(f"{data.get('screened_count', 0):,}", "Stocks Tracked"),
        _kpi_card(f"{data.get('zombie_count', 0):,}", "Zombies Flagged", change_sign="-"),
        _kpi_card(f"{data.get('quality_count', 0):,}", "Quality Stocks", change_sign="+"),
        _kpi_card("v1.0", "Suite Version"),
    ]


@callback(
    Output("dash-market-row", "children"),
    Input("dash-data-store", "data"),
)
def update_market_row(data):
    if not data:
        return []
    cards = data.get("market_cards", [])
    return [_market_card(c["label"], c.get("value"), c.get("change_pct")) for c in cards]


@callback(
    Output("dash-metals-row", "children"),
    Input("dash-data-store", "data"),
)
def update_metals_row(data):
    if not data:
        return []
    prices = data.get("metal_prices", [])
    return [_metal_card(p["metal"], p.get("price"), p.get("obs_date")) for p in prices]


@callback(
    Output("dash-gs-ratio", "children"),
    Input("dash-data-store", "data"),
)
def update_gs_ratio(data):
    if not data:
        return "—"
    ratio = data.get("gold_silver_ratio")
    if ratio is None:
        return html.Div([
            html.Div("—", className="kpi-value"),
            html.Div("No data", className="kpi-label"),
        ])
    return html.Div([
        html.Div(f"{ratio:.1f}x", className="kpi-value", style={"fontSize": "2.5rem", "color": "#f0c040"}),
        html.Div("Gold / Silver Ratio", className="kpi-label"),
        html.Div(
            "Historical avg ~65–70x",
            style={"fontSize": "0.72rem", "color": "#ffffff", "marginTop": "4px"},
        ),
    ])


# ---------------------------------------------------------------------------
# Macro formatting helpers
# ---------------------------------------------------------------------------

# series_id -> (unit_suffix, scale, desc)
_MACRO_META: dict[str, tuple[str, float, str]] = {
    "FEDFUNDS":      ("%",   1,          "Federal Funds Effective Rate — the overnight inter-bank lending rate set by the Fed"),
    "UNRATE":        ("%",   1,          "Unemployment Rate — % of labour force that is jobless and actively seeking work"),
    "VIXCLS":        ("",    1,          "CBOE VIX — 30-day implied volatility of the S&P 500; measures market fear"),
    "T10Y2Y":        ("%",   1,          "10Y minus 2Y Treasury yield spread — negative (inversion) signals recession risk"),
    "CPIAUCSL":      ("",    1,          "Consumer Price Index — measures inflation; compare YoY change, not level"),
    "WALCL":         ("$T",  1_000,      "Fed Balance Sheet — total assets held by the Federal Reserve (Trillions USD)"),
    "M2SL":          ("$T",  1_000,      "M2 Money Supply — cash + savings + money-market funds (Trillions USD)"),
    "M1SL":          ("$T",  1_000,      "M1 Money Supply — physical cash + demand deposits (Trillions USD)"),
    "RRPONTSYD":     ("$B",  1,          "Overnight Reverse Repo — cash parked at the Fed overnight (Billions USD); high = excess liquidity"),
    "WDTGAL":        ("$B",  1,          "Treasury General Account — Treasury's operating cash balance at the Fed (Billions USD)"),
    "DCOILWTICO":    ("$/bbl", 1,        "WTI Crude Oil spot price (USD per barrel)"),
    "PCEPILFE":      ("%",   1,          "Core PCE Inflation (ex Food & Energy) — the Fed's preferred inflation gauge"),
    "BAMLH0A0HYM2":  ("%",   1,          "High-Yield Credit Spread (OAS) — extra yield vs Treasuries; high = credit stress"),
    "T10YIE":        ("%",   1,          "10-Year Breakeven Inflation — bond-market's 10-year inflation expectation"),
    "ICSA":          ("K",   1_000,      "Initial Jobless Claims — new weekly unemployment filings (thousands)"),
    "DGS10":         ("%",   1,          "10-Year Treasury Yield"),
    "DGS2":          ("%",   1,          "2-Year Treasury Yield"),
}

# series_id -> callable(value) -> colour | None
def _macro_color(series_id: str, value: float | None) -> str:
    if value is None:
        return "#ffffff"
    rules = {
        "VIXCLS":       lambda v: "#e74c3c" if v > 25 else ("#2ecc71" if v < 15 else "#ffffff"),
        "UNRATE":       lambda v: "#e74c3c" if v > 5 else ("#2ecc71" if v < 4 else "#ffffff"),
        "FEDFUNDS":     lambda v: "#e74c3c" if v > 5 else ("#2ecc71" if v < 2 else "#ffffff"),
        "T10Y2Y":       lambda v: "#e74c3c" if v < 0 else ("#2ecc71" if v > 0.5 else "#ffffff"),
        "BAMLH0A0HYM2": lambda v: "#e74c3c" if v > 5 else ("#2ecc71" if v < 3 else "#ffffff"),
        "T10YIE":       lambda v: "#e74c3c" if v > 3 else ("#2ecc71" if v < 2 else "#ffffff"),
        "PCEPILFE":     lambda v: "#e74c3c" if v > 3 else ("#2ecc71" if v < 2 else "#ffffff"),
        "CPIAUCSL":     lambda v: "#ffffff",  # level not meaningful; show neutral
    }
    fn = rules.get(series_id)
    return fn(value) if fn else "#ffffff"


def _fmt_macro_value(series_id: str, value: float | None) -> str:
    if value is None:
        return "—"
    meta = _MACRO_META.get(series_id)
    if not meta:
        return f"{value:.4g}"
    unit, scale, _ = meta
    scaled = value / scale
    if unit == "$T":
        return f"${scaled:.2f}T"
    if unit == "$B":
        return f"${scaled:,.0f}B"
    if unit == "$/bbl":
        return f"${scaled:.2f}/bbl"
    if unit == "K":
        return f"{scaled:,.0f}K"
    if unit == "%":
        return f"{scaled:.2f}%"
    return f"{value:.4g}"


@callback(
    Output("dash-macro-table", "children"),
    Input("dash-data-store", "data"),
)
def update_macro_table(data):
    if not data:
        return html.P("No macro data.", style={"color": "#ffffff"})
    macro = data.get("macro_values", [])
    if not macro:
        return html.P("No macro data — run Admin > Refresh Macro.", style={"color": "#ffffff"})

    rows = []
    for m in macro:
        sid   = m.get("series_id", "")
        val   = m.get("value")
        color = _macro_color(sid, val)
        desc  = (_MACRO_META.get(sid) or (None, None, ""))[2]
        rows.append(html.Tr([
            html.Td(
                [
                    html.Span(m["name"], style={"color": "#cccccc"}),
                    html.Span(
                        f" — {desc}" if desc else "",
                        style={"color": "#555555", "fontSize": "0.72rem"},
                    ),
                ],
                style={"paddingRight": "20px", "whiteSpace": "normal", "wordBreak": "break-word"},
            ),
            html.Td(
                _fmt_macro_value(sid, val),
                style={"color": color, "textAlign": "right", "fontWeight": "600",
                       "whiteSpace": "nowrap"},
            ),
            html.Td(
                m.get("obs_date", ""),
                style={"color": "#555555", "paddingLeft": "16px", "fontSize": "0.74rem",
                       "whiteSpace": "nowrap"},
            ),
        ]))

    return dbc.Table(
        [html.Tbody(rows)],
        bordered=False,
        hover=True,
        size="sm",
        style={"backgroundColor": "#111111"},
    )
