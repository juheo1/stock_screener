"""
frontend.pages.screener_rok
===========================
Page – Stock Screener ROK (Republic of Korea).

Identical layout to the US Stock Screener, restricted to Korean-listed
tickers (KOSPI .KS / KOSDAQ .KQ).  All API calls pass region="rok".
"""

from __future__ import annotations

import dash
import dash_ag_grid as dag
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, dcc, html

from frontend.api_client import get_screener
from frontend.config import API_BASE_URL

dash.register_page(
    __name__,
    path="/screener-rok",
    name="Screener ROK",
    title="Stock Screener - ROK",
)


# ---------------------------------------------------------------------------
# Helper: build KRX ticker list with suffix
# ---------------------------------------------------------------------------

def _build_krx_tickers(raw_input: str, suffix: str) -> list[str]:
    """Convert a comma-separated raw input string to a list of KRX tickers.

    Each token is uppercased and trimmed.  If a token already ends with a
    recognised exchange suffix (``.KS`` or ``.KQ``) it is kept as-is;
    otherwise ``suffix`` is appended.

    Parameters
    ----------
    raw_input : str
        Raw text from the ticker input box, e.g. ``"005930, 000660.KS"``.
    suffix : str
        Default exchange suffix to append, e.g. ``".KS"`` or ``".KQ"``.

    Returns
    -------
    list[str]
        Fully-qualified KRX tickers, e.g. ``["005930.KQ", "000660.KS"]``.
    """
    tokens = [t.strip().upper() for t in raw_input.replace(",", " ").split() if t.strip()]
    return [
        t if t.endswith(".KS") or t.endswith(".KQ") else t + suffix
        for t in tokens
    ]

# ---------------------------------------------------------------------------
# AG Grid column definitions  (identical to US screener)
# ---------------------------------------------------------------------------

_COLUMNS = [
    {"field": "ticker",   "headerName": "Ticker",  "width": 90,  "pinned": "left",
     "tooltipField": "description",
     "headerTooltip": "Hover over a ticker to read the company's business description."},
    {"field": "name",     "headerName": "Company", "minWidth": 150, "flex": 2,
     "wrapText": True, "autoHeight": True},
    {"field": "sector",   "headerName": "Sector",  "minWidth": 110, "flex": 1,
     "wrapText": True, "autoHeight": True},
    {
        "field": "period_end",
        "headerName": "Period",
        "width": 82,
        "valueFormatter": {"function": "params.value ? params.value.slice(2) : '—'"},
    },
    # ---- Core quality metrics ----
    {
        "field": "quality_score",
        "headerName": "Score",
        "width": 80,
        "type": "numericColumn",
        "headerTooltip": (
            "Quality Score (0–100)\n\n"
            "Composite score identical to the Batch Compare page.  Each of the five "
            "core metrics earns up to 20 points:\n"
            "  Gross Margin ≥ 40%  → 20 pts  (neutral ≥ 15%  → 10 pts)\n"
            "  ROIC ≥ 12%          → 20 pts  (neutral ≥ 5%   → 10 pts)\n"
            "  FCF Margin ≥ 10%    → 20 pts  (neutral > 0%   → 10 pts)\n"
            "  Int. Coverage ≥ 3×  → 20 pts  (neutral > 1×   → 10 pts)\n"
            "  P/E ≤ 15            → 20 pts  (neutral < 40   → 10 pts)\n\n"
            "80–100: high quality  |  50–79: acceptable  |  < 50: weak"
        ),
        "valueFormatter": {"function": "params.value != null ? params.value.toFixed(0) : '—'"},
        "cellStyle": {
            "function": (
                "params.value != null ? ("
                "  params.value >= 80 ? {color: '#2ecc71', fontWeight: 600} :"
                "  params.value >= 50 ? {color: '#f39c12', fontWeight: 600} :"
                "  {color: '#e67e22', fontWeight: 600, fontStyle: 'italic'}"
                ") : {}"
            )
        },
    },
    {
        "field": "gross_margin",
        "headerName": "Gross Margin %",
        "width": 130,
        "type": "numericColumn",
        "headerTooltip": (
            "Gross Margin = (Revenue − COGS) / Revenue × 100\n\n"
            "How much of each revenue dollar survives direct production costs.\n"
            "High gross margin signals pricing power and a durable competitive moat.\n\n"
            "Rough benchmarks:\n"
            "- Software / pharma  →  60–85%\n"
            "- Consumer brands  →  40–60%\n"
            "- Retail / manufacturing  →  20–40%\n"
            "- Commodities / distribution  →  < 20%\n\n"
            "Red flags:\n"
            "- Sudden compression warrants investigation (competition, input costs).\n"
            "- Trending downward over 3+ years is a moat-erosion signal.\n\n"
            "Period view:\n"
            "- Annual  →  full fiscal year (most stable).\n"
            "- Quarterly  →  single quarter; useful for spotting inflections early."
        ),
        "valueFormatter": {"function": "params.value != null ? params.value.toFixed(1) + '%' : '—'"},
        "cellStyle": {
            "function": (
                "params.data.gm_pass ? {color: '#2ecc71', fontWeight: 600} : "
                "{color: '#e67e22', fontWeight: 600, fontStyle: 'italic'}"
            )
        },
    },
    {
        "field": "roic",
        "headerName": "ROIC",
        "width": 90,
        "type": "numericColumn",
        "headerTooltip": (
            "Return on Invested Capital\n"
            "= NOPAT / Invested Capital\n"
            "  NOPAT = EBIT × (1 − effective tax rate)\n"
            "  Invested Capital = Equity + Debt − Cash\n\n"
            "The gold-standard efficiency metric.  Unlike ROE, ROIC is not inflated\n"
            "by leverage or buybacks — it measures pure operational value creation.\n\n"
            "Interpretation:\n"
            "- ROIC > cost of capital (~8–10%)  →  value-creating business\n"
            "- ROIC < cost of capital  →  value-destroying (even if profitable)\n"
            "- ROIC > 15% consistently  →  hallmark of a wide-moat business\n\n"
            "Compare to ROE: a wide ROE−ROIC gap often means leverage is doing\n"
            "the heavy lifting rather than operational excellence.\n\n"
            "Period view:\n"
            "- Annual  →  full-year EBIT and year-end balance sheet (most stable).\n"
            "- Quarterly  →  captures the latest capital decisions; noisier."
        ),
        "valueFormatter": {"function": "params.value != null ? (params.value * 100).toFixed(1) + '%' : '—'"},
        "cellStyle": {
            "function": "params.data.roic_pass ? {color: '#2ecc71', fontWeight: 600} : {color: '#e67e22', fontWeight: 600, fontStyle: 'italic'}"
        },
    },
    {
        "field": "fcf_margin",
        "headerName": "FCF Margin %",
        "width": 120,
        "type": "numericColumn",
        "headerTooltip": (
            "FCF Margin = (Operating Cash Flow − CapEx) / Revenue × 100\n\n"
            "Earnings can be massaged; cash cannot.  FCF margin reveals the fraction\n"
            "of revenue that converts to real cash available for shareholders.\n\n"
            "Interpretation:\n"
            "- > 10%  →  strong; business is highly self-funding\n"
            "- 5–10%  →  healthy for most industries\n"
            "- 0–5%  →  marginal; monitor closely\n"
            "- Negative  →  burning cash; acceptable for high-growth if improving\n\n"
            "Red flags:\n"
            "- Chronically negative FCF with no improvement path.\n"
            "- Large gap between net income and FCF (earnings quality concern).\n\n"
            "Period view:\n"
            "- Annual  →  smooths lumpy capex cycles (preferred for trend analysis).\n"
            "- Quarterly  →  one large one-time capex can distort; check trend."
        ),
        "valueFormatter": {"function": "params.value != null ? params.value.toFixed(1) + '%' : '—'"},
        "cellStyle": {
            "function": "params.data.fcf_pass ? {color: '#2ecc71', fontWeight: 600} : {color: '#e67e22', fontWeight: 600, fontStyle: 'italic'}"
        },
    },
    {
        "field": "interest_coverage",
        "headerName": "Int. Coverage",
        "width": 120,
        "type": "numericColumn",
        "headerTooltip": (
            "Interest Coverage = EBIT / Interest Expense\n\n"
            "How many times over the company can pay its interest bill from operating\n"
            "profit.  Think of it as the safety cushion above the break-even point.\n\n"
            "Thresholds:\n"
            "- > 5×  →  comfortable; ample buffer against earnings decline\n"
            "- 3–5×  →  healthy for most industries\n"
            "- 1.5–3×  →  thin; any earnings slip raises default risk\n"
            "- < 1.5×  →  distress territory; can't cover interest from earnings\n"
            "- N/A (—)  →  no interest-bearing debt (no debt is not a red flag)\n\n"
            "Context:\n"
            "- Utilities and REITs structurally carry higher debt; use sector comps.\n"
            "- Falling coverage trend is more alarming than a single low reading.\n\n"
            "Period view:\n"
            "- Annual  →  full-year EBIT vs annual interest (most stable).\n"
            "- Quarterly  →  a one-off weak quarter can mislead; check the trend."
        ),
        "valueFormatter": {"function": "params.value != null ? params.value.toFixed(2) + 'x' : '—'"},
        "cellStyle": {
            "function": "params.data.ic_pass ? {color: '#2ecc71', fontWeight: 600} : {color: '#e67e22', fontWeight: 600, fontStyle: 'italic'}"
        },
    },
    {
        "field": "pe_ratio",
        "headerName": "P/E",
        "width": 80,
        "type": "numericColumn",
        "headerTooltip": (
            "P/E Ratio = Share Price / Diluted EPS\n\n"
            "The market's valuation multiple — how much you pay per dollar of earnings.\n\n"
            "Rough benchmarks:\n"
            "- < 10  →  deep value or low-growth / cyclical business\n"
            "- 10–20  →  fair value range for many mature businesses\n"
            "- 20–35  →  growth premium; requires execution\n"
            "- > 40  →  pricing in significant future growth; high risk if missed\n"
            "- N/A (—)  →  earnings negative (loss-making); P/E not meaningful\n\n"
            "Important:\n"
            "- Always compare within the same sector (30× is cheap for software,\n"
            "  expensive for steel).\n"
            "- Pair P/E with P/B and Graham Number for a fuller valuation picture.\n\n"
            "Period view:\n"
            "- Annual  →  Price ÷ full-year EPS (classic trailing P/E).\n"
            "- Quarterly  →  Price ÷ (quarterly EPS × 4); faster-reacting but\n"
            "  noisy for seasonal businesses (e.g. retailers heavy in Q4)."
        ),
        "valueFormatter": {"function": "params.value != null ? params.value.toFixed(1) : '—'"},
        "cellStyle": {
            "function": "params.data.pe_pass ? {color: '#2ecc71', fontWeight: 600} : {color: '#e67e22', fontWeight: 600, fontStyle: 'italic'}"
        },
    },
    # ---- Valuation metrics ----
    {
        "field": "pb_ratio",
        "headerName": "P/B",
        "width": 80,
        "type": "numericColumn",
        "headerTooltip": (
            "P/B Ratio = Market Cap / Total Equity\n"
            "(equivalently: Price / Book Value per Share)\n\n"
            "How much the market pays for each dollar of accounting net worth.\n\n"
            "Interpretation:\n"
            "- < 1.0  →  trades below book value; deep-value signal or impairment\n"
            "- 1–3  →  typical for capital-intensive industries\n"
            "- 3–10  →  growth or asset-light premium\n"
            "- > 10  →  heavy intangible/franchise value (software, luxury brands)\n\n"
            "Caveat: asset-light businesses (software, pharma) carry high P/B because\n"
            "intangible assets (brand, IP, talent) are not on the balance sheet.\n"
            "Compare P/B within the same industry for meaningful context.\n\n"
            "Graham's combined criterion: P/E × P/B ≤ 22.5 (see P/E×P/B column)."
        ),
        "valueFormatter": {"function": "params.value != null ? params.value.toFixed(2) : '—'"},
    },
    {
        "field": "pe_x_pb",
        "headerName": "P/E×P/B",
        "width": 95,
        "type": "numericColumn",
        "headerTooltip": (
            "P/E × P/B — Graham's Combined Valuation Criterion\n\n"
            "Benjamin Graham suggested that the product P/E × P/B should not exceed 22.5 "
            "(reflecting P/E ≤ 15 and P/B ≤ 1.5 jointly).  This is mathematically "
            "equivalent to the stock trading at or below its Graham Number:\n"
            "  Graham Number = √(22.5 × EPS × Book Value/Share)\n\n"
            "Green when P/E × P/B ≤ 22.5 (Graham criterion satisfied).  "
            "Only meaningful when both P/E and P/B are positive."
        ),
        "valueFormatter": {"function": "params.value != null ? params.value.toFixed(1) : '—'"},
        "cellStyle": {
            "function": (
                "params.value != null ? ("
                "  params.value <= 22.5 ? {color: '#2ecc71', fontWeight: 600} : {}"
                ") : {}"
            )
        },
    },
    {
        "field": "graham_number",
        "headerName": "Graham #",
        "width": 100,
        "type": "numericColumn",
        "headerTooltip": (
            "Graham Number = √(22.5 × EPS × BVPS)\n\n"
            "Benjamin Graham's upper price bound for a defensive investor.  "
            "BVPS = Book Value per Share = Total Equity / Diluted Shares.\n\n"
            "If Current Price ≤ Graham Number, the stock satisfies Graham's combined "
            "valuation criterion (P/E ≤ 15 AND P/B ≤ 1.5).  "
            "Requires positive EPS and positive book value; shows '—' otherwise.\n\n"
            "Compare this number to the Price column: a Graham Number significantly "
            "above the current price suggests potential undervaluation on a pure "
            "asset-and-earnings basis."
        ),
        "valueFormatter": {"function": "params.value != null ? params.value.toFixed(0) : '—'"},
        "cellStyle": {
            "function": (
                "params.data.current_price != null && params.value != null ? ("
                "  params.data.current_price <= params.value ? {color: '#2ecc71', fontWeight: 600} : {}"
                ") : {}"
            )
        },
    },
    # ---- Net-net / balance-sheet safety ----
    {
        "field": "ncav_per_share",
        "headerName": "NCAV/Shr",
        "width": 100,
        "type": "numericColumn",
        "headerTooltip": (
            "Net Current Asset Value per Share\n\n"
            "NCAV = Current Assets − Total Liabilities (all liabilities, not just current)\n"
            "NCAV/Share = NCAV / Diluted Shares Outstanding\n\n"
            "Graham's net-net criterion: Price ≤ (2/3) × NCAV/Share suggests "
            "the stock can be bought below liquidation value with a margin of safety.  "
            "Such stocks are rare in modern markets but can signal deep undervaluation "
            "or distress.  The 'Net-Net' column flags when this condition is met.\n\n"
            "Negative NCAV means liabilities exceed all current assets — a financial "
            "health warning."
        ),
        "valueFormatter": {"function": "params.value != null ? params.value.toFixed(0) : '—'"},
    },
    {
        "field": "net_net_flag",
        "headerName": "Net-Net",
        "width": 88,
        "headerTooltip": (
            "Net-Net Buy Signal\n\n"
            "TRUE when Current Price ≤ (2/3) × NCAV per Share.  "
            "This is Benjamin Graham's strict net-net criterion: the stock trades at "
            "a meaningful discount to its liquidation value, providing a margin of "
            "safety even if the business earns nothing going forward.\n\n"
            "Such opportunities are very rare in large-cap markets but can appear in "
            "micro-cap, distressed, or neglected segments."
        ),
        "valueFormatter": {"function": "params.value === true ? 'Yes' : (params.value === false ? 'No' : '—')"},
        "cellStyle": {
            "function": (
                "params.value === true ? {color: '#2ecc71', fontWeight: 600} : "
                "{color: '#888888'}"
            )
        },
    },
    {
        "field": "current_ratio",
        "headerName": "Curr. Ratio",
        "width": 105,
        "type": "numericColumn",
        "headerTooltip": (
            "Current Ratio = Current Assets / Current Liabilities\n\n"
            "Measures short-term liquidity.  A ratio ≥ 2.0 is conservatively strong; "
            "1.0–2.0 is adequate for most industries; below 1.0 means current liabilities "
            "exceed current assets, which can signal liquidity risk.\n\n"
            "Context matters: lean manufacturers and retailers deliberately operate with "
            "ratios near 1.0 (JIT inventory, fast receivable turnover), while holding "
            "companies or utilities may need higher cushions."
        ),
        "valueFormatter": {"function": "params.value != null ? params.value.toFixed(2) : '—'"},
        "cellStyle": {
            "function": (
                "params.value != null ? ("
                "  params.value >= 2.0 ? {color: '#2ecc71', fontWeight: 600} :"
                "  params.value >= 1.0 ? {} :"
                "  {color: '#e67e22', fontWeight: 600, fontStyle: 'italic'}"
                ") : {}"
            )
        },
    },
    {
        "field": "ltd_lte_nca",
        "headerName": "LTD ≤ NCA",
        "width": 100,
        "headerTooltip": (
            "Long-Term Debt ≤ Net Current Assets\n\n"
            "Net Current Assets (NCA) = Current Assets − Current Liabilities = Working Capital\n\n"
            "When long-term debt is fully covered by net current assets, the company could "
            "theoretically pay off its long-term obligations from liquid assets alone.  "
            "This is a conservative balance-sheet test from Graham's 'The Intelligent Investor'.\n\n"
            "TRUE (green) = financially conservative balance sheet.  "
            "FALSE = long-term debt exceeds the liquid cushion (common and not necessarily alarming; "
            "assess alongside interest coverage and cash generation)."
        ),
        "valueFormatter": {"function": "params.value === true ? 'Yes' : (params.value === false ? 'No' : '—')"},
        "cellStyle": {
            "function": (
                "params.value === true ? {color: '#2ecc71', fontWeight: 600} : "
                "{color: '#888888'}"
            )
        },
    },
    # ---- Return / earnings quality ----
    {
        "field": "roe",
        "headerName": "ROE",
        "width": 80,
        "type": "numericColumn",
        "headerTooltip": (
            "Return on Equity = Net Income / Total Equity\n\n"
            "Measures how effectively management generates profit from shareholders' capital.  "
            "A high ROE (> 15%) can indicate a competitive advantage, but also warrants scrutiny:\n\n"
            "  • Share buybacks reduce equity, inflating ROE without operational improvement.\n"
            "  • High leverage amplifies ROE (DuPont: ROE = Profit Margin × Asset Turnover × Equity Multiplier).\n"
            "  • Compare with ROIC: if ROIC is modest but ROE is high, leverage or buybacks "
            "    are likely the driver — see the 'ROE Levered?' column.\n\n"
            "A durable high ROE supported by high ROIC and reasonable debt is the gold standard."
        ),
        "valueFormatter": {"function": "params.value != null ? (params.value * 100).toFixed(1) + '%' : '—'"},
    },
    {
        "field": "owner_earnings_per_share",
        "headerName": "OE/Shr",
        "width": 90,
        "type": "numericColumn",
        "headerTooltip": (
            "Owner Earnings per Share (Buffett Approximation)\n\n"
            "Owner Earnings = Net Income + Depreciation & Amortization − Maintenance CapEx\n\n"
            "Proxy used here: all reported CapEx is treated as maintenance CapEx.  "
            "Standard financial filings do not separately disclose maintenance vs growth CapEx; "
            "D&A is used as the non-cash charge add-back.  Growth-heavy businesses will have "
            "OE understated relative to their true owner earnings.\n\n"
            "Formula: OE = Net Income + D&A + CapEx  (CapEx is negative in DB)\n"
            "         OE/Share = OE / Diluted Shares\n\n"
            "This is numerically identical to FCF per share when all CapEx is maintenance spend.  "
            "Compare to EPS: if OE/Shr > EPS consistently, the business is cash-generative; "
            "if OE/Shr < EPS, reported earnings are running ahead of real cash returns."
        ),
        "valueFormatter": {"function": "params.value != null ? params.value.toFixed(0) : '—'"},
    },
    {
        "field": "roe_leveraged",
        "headerName": "ROE Levered?",
        "width": 115,
        "headerTooltip": (
            "ROE Leverage Flag\n\n"
            "Flagged TRUE when ROE > 15% AND Debt-to-Equity ratio > 2.0.\n\n"
            "High ROE driven by high leverage can mislead: a company borrowing heavily "
            "amplifies equity returns without improving underlying business economics.  "
            "When buybacks or debt fuel ROE, the metric loses predictive power for "
            "future shareholder value creation.\n\n"
            "Cross-reference with ROIC: a wide gap between ROE and ROIC indicates "
            "financial engineering rather than operational excellence.\n\n"
            "Not flagged (—) when ROE ≤ 15% or D/E data is unavailable."
        ),
        "valueFormatter": {"function": "params.value === true ? 'Levered' : '—'"},
        "cellStyle": {
            "function": (
                "params.value === true ? {color: '#e67e22', fontWeight: 600, fontStyle: 'italic'} : "
                "{color: '#888888'}"
            )
        },
    },
    # ---- Price ----
    {
        "field": "current_price",
        "headerName": "Price (KRW)",
        "width": 110,
        "type": "numericColumn",
        "valueFormatter": {"function": "params.value != null ? params.value.toLocaleString('ko-KR') : '—'"},
    },
]

_DEFAULT_COL = {
    "sortable": True,
    "filter": True,
    "resizable": True,
    "wrapText": True,
    "autoHeight": True,
    "cellStyle": {"backgroundColor": "transparent", "color": "#ffffff",
                  "whiteSpace": "normal", "lineHeight": "1.4"},
}


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------

def _thresh(label: str, comp_id: str, placeholder: str, step: float = 0.1) -> html.Div:
    return html.Div([
        html.Div(label, style={"fontSize": "0.70rem", "color": "#888888", "marginBottom": "3px"}),
        dbc.Input(
            id=comp_id,
            type="number",
            placeholder=placeholder,
            step=step,
            debounce=True,
            size="sm",
            style={"backgroundColor": "#0d0d0d", "color": "#ffffff",
                   "border": "1px solid #2a2a2a", "padding": "4px 8px"},
        ),
    ])


def _section(text: str) -> html.Div:
    return html.Div(text, style={
        "fontSize": "0.68rem", "fontWeight": 700, "letterSpacing": "0.08em",
        "color": "#666666", "textTransform": "uppercase", "marginBottom": "6px",
    })


layout = html.Div([
    # Title
    html.Div([
        html.Span("Stock Screener ", className="page-title"),
        html.Span("ROK", className="page-title title-accent"),
    ], style={"marginBottom": "14px"}),

    dcc.Store(id="rok-screener-period", data="quarterly"),

    # -----------------------------------------------------------------------
    # Collapsible filter panel
    # -----------------------------------------------------------------------
    html.Div([
        dbc.Button(
            [
                html.Span(id="rok-filter-arrow", children="▼",
                          style={"marginRight": "6px", "fontSize": "0.75rem"}),
                "Screen Filters",
            ],
            id="rok-filter-toggle",
            color="link",
            size="sm",
            style={
                "color": "#aaaaaa", "textDecoration": "none", "fontWeight": 600,
                "fontSize": "0.82rem", "padding": "8px 14px", "letterSpacing": "0.04em",
                "width": "100%", "textAlign": "left",
                "backgroundColor": "#111111", "border": "1px solid #2a2a2a",
                "borderRadius": "4px 4px 0 0",
            },
        ),

        dbc.Collapse(
            html.Div([
                dbc.Row([
                    # Period view
                    dbc.Col([
                        _section("Period"),
                        html.Div([
                            dbc.Button("Quarterly", id="rok-period-quarterly", size="sm",
                                       color="primary", outline=False, className="preset-btn",
                                       style={"marginRight": "4px", "marginBottom": "4px"}),
                            dbc.Button("Annual",    id="rok-period-annual",    size="sm",
                                       color="primary", outline=True,  className="preset-btn",
                                       style={"marginBottom": "4px"}),
                        ]),
                    ], md=1, style={"borderRight": "1px solid #222", "paddingRight": "14px"}),

                    # Quick presets
                    dbc.Col([
                        _section("Quick Presets"),
                        html.Div([
                            dbc.Button("High Quality", id="rok-preset-quality", size="sm",
                                       color="success", outline=True, className="preset-btn",
                                       title="High Quality: GM ≥ 40%, ROIC ≥ 10%, FCF ≥ 5%, Coverage ≥ 3×, P/E ≤ 35",
                                       style={"marginRight": "4px", "marginBottom": "4px"}),
                            dbc.Button("Value",        id="rok-preset-value",   size="sm",
                                       color="info",    outline=True, className="preset-btn",
                                       title="Value: GM ≥ 20%, ROIC ≥ 5%, FCF ≥ 0%, Coverage ≥ 2×, P/E ≤ 15",
                                       style={"marginRight": "4px", "marginBottom": "4px"}),
                            dbc.Button("Growth",       id="rok-preset-growth",  size="sm",
                                       color="warning", outline=True, className="preset-btn",
                                       title="Growth: GM ≥ 50%, ROIC ≥ 8%, FCF ≥ -5%, P/E ≤ 60 (no coverage filter)",
                                       style={"marginRight": "4px", "marginBottom": "4px"}),
                            dbc.Button("QT Regime", id="rok-preset-qt-regime", size="sm",
                                       color="danger", outline=True, className="preset-btn",
                                       title="QT Regime: GM ≥ 45%, ROIC ≥ 12%, FCF ≥ 8%, Coverage ≥ 4×, P/E ≤ 25 — tighter filters for Fed tightening cycle",
                                       style={"marginRight": "4px", "marginBottom": "4px"}),
                            dbc.Button("QE Regime", id="rok-preset-qe-regime", size="sm",
                                       color="success", outline=True, className="preset-btn",
                                       title="QE Regime: GM ≥ 30%, ROIC ≥ 6%, FCF ≥ 0%, Coverage ≥ 2×, P/E ≤ 50 — relaxed filters for Fed easing cycle",
                                       style={"marginRight": "4px", "marginBottom": "4px"}),
                            dbc.Button("Recession Defense", id="rok-preset-recession", size="sm",
                                       color="secondary", outline=True, className="preset-btn",
                                       title="Recession Defense: GM ≥ 50%, ROIC ≥ 15%, FCF ≥ 10%, Coverage ≥ 5×, P/E ≤ 20 — defensive filters for recessionary conditions",
                                       style={"marginRight": "4px", "marginBottom": "4px"}),
                            dbc.Button("Clear",        id="rok-preset-clear",   size="sm",
                                       color="secondary", className="preset-btn",
                                       style={"marginBottom": "4px"}),
                        ]),
                    ], md=3, style={"borderRight": "1px solid #222", "paddingRight": "14px"}),

                    # Threshold inputs
                    dbc.Col([
                        _section("Thresholds"),
                        dbc.Row([
                            dbc.Col(_thresh("Min GM %",        "rok-th-gross-margin",  "e.g. 40"),          md=4),
                            dbc.Col(_thresh("Min ROIC",        "rok-th-roic",          "e.g. 0.10", 0.01),  md=4),
                            dbc.Col(_thresh("Min FCF %",       "rok-th-fcf-margin",    "e.g. 5"),           md=4),
                        ], className="g-2 mb-2"),
                        dbc.Row([
                            dbc.Col(_thresh("Min Int. Cov. (x)", "rok-th-int-coverage", "e.g. 3"),          md=3),
                            dbc.Col(_thresh("Max P/E",           "rok-th-pe",           "e.g. 35"),          md=3),
                            dbc.Col(_thresh("Min Score (0–100)", "rok-th-score",        "e.g. 60", 1.0),     md=3),
                            dbc.Col(
                                dbc.Checklist(
                                    options=[{"label": " Hide N/A", "value": "hide_na"}],
                                    value=[],
                                    id="rok-hide-na-check",
                                    switch=True,
                                    style={"color": "#aaaaaa", "fontSize": "0.82rem",
                                           "marginTop": "20px"},
                                ), md=3
                            ),
                        ], className="g-2"),
                    ], md=5, style={"borderRight": "1px solid #222", "paddingRight": "14px"}),

                    # Data management
                    dbc.Col([
                        _section("Data — KRX Tickers"),
                        dbc.InputGroup([
                            dbc.Input(
                                id="rok-add-tickers-input",
                                placeholder="005930, 000660 …",
                                size="sm",
                                style={"backgroundColor": "#0d0d0d", "color": "#ffffff",
                                       "border": "1px solid #2a2a2a"},
                            ),
                            dbc.Select(
                                id="rok-exchange-suffix",
                                options=[
                                    {"label": "KOSPI (.KS)", "value": ".KS"},
                                    {"label": "KOSDAQ (.KQ)", "value": ".KQ"},
                                ],
                                value=".KS",
                                size="sm",
                                style={"backgroundColor": "#0d0d0d", "color": "#ffffff",
                                       "border": "1px solid #2a2a2a", "maxWidth": "130px"},
                            ),
                        ], style={"marginBottom": "6px"}),
                        dbc.Row([
                            dbc.Col(dbc.Button("Add & Fetch",  id="rok-add-tickers-btn",
                                               color="primary",   size="sm",
                                               style={"width": "100%"}), md=4),
                            dbc.Col(dbc.Button("Refresh All",  id="rok-refresh-all-btn",
                                               color="warning",   size="sm", outline=True,
                                               style={"width": "100%"},
                                               title="Re-fetch all KRX tickers"), md=4),
                            dbc.Col(dbc.Button("Recompute",    id="rok-recompute-btn",
                                               color="secondary", size="sm", outline=True,
                                               style={"width": "100%"}), md=4),
                        ], className="g-1 mb-2"),
                        dbc.InputGroup([
                            dbc.Input(
                                id="rok-remove-ticker-input",
                                placeholder="e.g. 005930.KS",
                                size="sm",
                                style={"backgroundColor": "#0d0d0d", "color": "#ffffff",
                                       "border": "1px solid #2a2a2a"},
                            ),
                            dbc.Button("Remove", id="rok-remove-ticker-btn",
                                       color="danger", size="sm", outline=True),
                        ]),
                        dcc.Loading(html.Div(id="rok-admin-status",
                                             style={"marginTop": "6px", "fontSize": "0.78rem",
                                                    "color": "#2ecc71"})),
                    ], md=3),
                ], className="g-3"),
            ], style={"backgroundColor": "#111111", "padding": "14px 16px",
                      "border": "1px solid #2a2a2a", "borderTop": "none",
                      "borderRadius": "0 0 4px 4px"}),
            id="rok-filter-collapse",
            is_open=True,
        ),
    ], style={"marginBottom": "14px"}),

    # -----------------------------------------------------------------------
    # Results
    # -----------------------------------------------------------------------
    dbc.Row([
        dbc.Col(
            dbc.InputGroup([
                dbc.InputGroupText(
                    html.I(className="bi-search"),
                    style={"backgroundColor": "#1a1a1a", "border": "1px solid #2a2a2a",
                           "color": "#888888"},
                ),
                dbc.Input(
                    id="rok-screener-search",
                    placeholder="Search ticker or company name…",
                    debounce=False,
                    size="sm",
                    style={"backgroundColor": "#111111", "color": "#ffffff",
                           "border": "1px solid #2a2a2a", "borderLeft": "none"},
                ),
            ]),
            md=5,
        ),
        dbc.Col(html.Div(id="rok-screener-meta",
                         style={"color": "#aaaaaa", "fontSize": "0.80rem",
                                "paddingTop": "6px"}), md=5),
        dbc.Col([
            html.A(
                dbc.Button([html.I(className="bi-download me-2"), "Export CSV"],
                           color="secondary", size="sm", outline=True),
                id="rok-screener-export-link",
                href=f"{API_BASE_URL}/screener/export?region=rok",
                target="_blank",
            ),
        ], md=2, style={"textAlign": "right"}),
    ], className="mb-2"),

    dcc.Loading(
        dag.AgGrid(
            id="rok-screener-grid",
            columnDefs=_COLUMNS,
            defaultColDef=_DEFAULT_COL,
            rowData=[],
            dashGridOptions={
                "pagination": True,
                "paginationPageSize": 50,
                "rowSelection": "single",
                "suppressCellFocus": True,
                "tooltipShowDelay": 400,
                "tooltipHideDelay": 12000,
                "tooltipInteraction": True,
            },
            style={"height": "75vh"},
            className="ag-theme-alpine-dark",
        ),
    ),
])


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

@callback(
    Output("rok-filter-collapse", "is_open"),
    Output("rok-filter-arrow",    "children"),
    Input("rok-filter-toggle",    "n_clicks"),
    State("rok-filter-collapse",  "is_open"),
    prevent_initial_call=True,
)
def rok_toggle_filters(_, is_open: bool):
    new_open = not is_open
    return new_open, "▼" if new_open else "▶"


@callback(
    Output("rok-th-gross-margin", "value"),
    Output("rok-th-roic",         "value"),
    Output("rok-th-fcf-margin",   "value"),
    Output("rok-th-int-coverage", "value"),
    Output("rok-th-pe",           "value"),
    Output("rok-th-score",        "value"),
    Input("rok-preset-quality",    "n_clicks"),
    Input("rok-preset-value",      "n_clicks"),
    Input("rok-preset-growth",     "n_clicks"),
    Input("rok-preset-clear",      "n_clicks"),
    Input("rok-preset-qt-regime",  "n_clicks"),
    Input("rok-preset-qe-regime",  "n_clicks"),
    Input("rok-preset-recession",  "n_clicks"),
    prevent_initial_call=True,
)
def rok_apply_preset(q, v, g, c, qt, qe, rec):
    trigger = dash.ctx.triggered_id
    presets = {
        "rok-preset-quality":    (40,   0.10,  5,    3.0,  35,   None),
        "rok-preset-value":      (20,   0.05,  0,    2.0,  15,   None),
        "rok-preset-growth":     (50,   0.08, -5,    None, 60,   None),
        "rok-preset-clear":      (None, None, None,  None, None, None),
        "rok-preset-qt-regime":  (45,   0.12,  8,    4.0,  25,   None),
        "rok-preset-qe-regime":  (30,   0.06,  0,    2.0,  50,   None),
        "rok-preset-recession":  (50,   0.15, 10,    5.0,  20,   None),
    }
    return presets.get(trigger, (None, None, None, None, None, None))


@callback(
    Output("rok-screener-period",  "data"),
    Output("rok-period-quarterly", "outline"),
    Output("rok-period-annual",    "outline"),
    Input("rok-period-quarterly",  "n_clicks"),
    Input("rok-period-annual",     "n_clicks"),
    prevent_initial_call=True,
)
def rok_toggle_period(q_clicks, a_clicks):
    period = "annual" if dash.ctx.triggered_id == "rok-period-annual" else "quarterly"
    return period, period == "annual", period == "quarterly"


@callback(
    Output("rok-screener-grid", "rowData"),
    Output("rok-screener-meta", "children"),
    Input("rok-th-gross-margin",  "value"),
    Input("rok-th-roic",          "value"),
    Input("rok-th-fcf-margin",    "value"),
    Input("rok-th-int-coverage",  "value"),
    Input("rok-th-pe",            "value"),
    Input("rok-th-score",         "value"),
    Input("rok-hide-na-check",    "value"),
    Input("rok-screener-period",  "data"),
    Input("rok-screener-search",  "value"),
)
def rok_update_screener(gm, roic, fcf, ic, pe, score, hide_na_val, period_type, search):
    period_type = period_type or "quarterly"
    hide_na = "hide_na" in (hide_na_val or [])
    result = get_screener(
        min_gross_margin=gm,
        min_roic=roic,
        min_fcf_margin=fcf,
        min_interest_coverage=ic,
        max_pe=pe,
        min_score=score,
        hide_na=hide_na,
        page_size=500,
        period_type=period_type,
        region="rok",
    )
    if not result:
        return [], "API unavailable."

    rows = result.get("rows", [])
    meta = result.get("meta", {})
    total = meta.get("total", 0)
    period_label = "Quarterly" if period_type == "quarterly" else "Annual"

    if search and search.strip():
        s = search.strip().lower()
        rows = [
            r for r in rows
            if s in (r.get("ticker") or "").lower()
            or s in (r.get("name") or "").lower()
        ]

    shown = len(rows)
    meta_text = f"Showing {shown} of {total:,} KRX stocks  ·  {period_label} view"
    if search and search.strip() and shown != total:
        meta_text += f"  ·  filtered by \"{search.strip()}\""
    return rows, meta_text


@callback(
    Output("rok-admin-status", "children"),
    Input("rok-add-tickers-btn",    "n_clicks"),
    Input("rok-refresh-all-btn",    "n_clicks"),
    Input("rok-recompute-btn",      "n_clicks"),
    Input("rok-remove-ticker-btn",  "n_clicks"),
    State("rok-add-tickers-input",  "value"),
    State("rok-exchange-suffix",    "value"),
    State("rok-remove-ticker-input", "value"),
    prevent_initial_call=True,
)
def rok_handle_admin(add_clicks, refresh_all_clicks, recompute_clicks, remove_clicks,
                     ticker_input, suffix, remove_input):
    trigger = dash.ctx.triggered_id
    if trigger == "rok-add-tickers-btn" and ticker_input:
        from frontend.api_client import admin_compute, admin_classify, admin_fetch
        suffix = suffix or ".KS"
        tickers = _build_krx_tickers(ticker_input, suffix)
        res = admin_fetch(tickers)
        if res:
            admin_compute(tickers=tickers)
            admin_classify(tickers=tickers)
            return f"Fetched & computed: {', '.join(tickers)}"
        return "Fetch failed — check API connection."
    elif trigger == "rok-refresh-all-btn":
        from frontend.api_client import admin_compute, admin_classify, admin_fetch, admin_list_tickers
        existing = admin_list_tickers()
        if not existing:
            return "No tickers in database to refresh."
        tickers = [
            row["ticker"] for row in existing
            if row["ticker"].endswith(".KS") or row["ticker"].endswith(".KQ")
        ]
        if not tickers:
            return "No KRX tickers in database."
        res = admin_fetch(tickers)
        if res:
            admin_compute(tickers=tickers)
            admin_classify(tickers=tickers)
            return f"Refreshed {len(tickers)} KRX tickers."
        return "Refresh failed — check API connection."
    elif trigger == "rok-recompute-btn":
        from frontend.api_client import admin_compute, admin_classify, admin_list_tickers
        existing = admin_list_tickers()
        krx_tickers = [
            row["ticker"] for row in (existing or [])
            if row["ticker"].endswith(".KS") or row["ticker"].endswith(".KQ")
        ]
        if not krx_tickers:
            return "No KRX tickers in database."
        admin_compute(tickers=krx_tickers)
        admin_classify(tickers=krx_tickers)
        return f"Recomputed metrics for {len(krx_tickers)} KRX ticker(s)."
    elif trigger == "rok-remove-ticker-btn" and remove_input:
        from frontend.api_client import admin_delete_ticker
        sym = remove_input.strip().upper()
        res = admin_delete_ticker(sym)
        if res:
            return f"Removed {sym} from database."
        return f"Remove failed — {sym} may not exist."
    return ""
