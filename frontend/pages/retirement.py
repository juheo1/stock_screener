"""
frontend.pages.retirement
=========================
Page – Sophisticated Retirement Planner.

Two separate buttons for two modes:
  1. "Generate Planning Summary" – fast deterministic pass.
     Required nest egg, required return rate, 401k/IRA-aware account breakdown.

  2. "Run Monte Carlo Simulation" – probability fan charts (conservative /
     expected / optimistic) showing P10/P50/P90 portfolio growth paths.

Dollar-amount inputs use type="text" / inputMode="numeric" to avoid the
browser scroll-wheel increment issue and React controlled-input quirks.
"""

from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from dash import Input, Output, State, callback, ctx, dcc, html, no_update
from dash.exceptions import PreventUpdate

from frontend.api_client import run_retirement

dash.register_page(
    __name__,
    path="/retirement",
    name="Retirement Planner",
    title="Retirement Planner",
)

# ---------------------------------------------------------------------------
# Style constants
# ---------------------------------------------------------------------------

_NUM_INPUT_STYLE = {
    "backgroundColor": "#111111",
    "color": "#ffffff",
    "border": "1px solid #2a2a2a",
    "borderRadius": "4px",
    "padding": "5px 10px",
    "width": "100%",
    "marginBottom": "10px",
    "outline": "none",
}

_SECTION_STYLE = {
    "fontSize": "0.72rem",
    "color": "#888",
    "textTransform": "uppercase",
    "letterSpacing": "0.8px",
    "marginTop": "14px",
    "marginBottom": "6px",
}

_SCENARIO_COLOURS = {
    "conservative": "#e74c3c",
    "expected":     "#4a90e2",
    "optimistic":   "#2ecc71",
}

# Tab bar styles (active / inactive)
_TAB_BASE = {
    "backgroundColor": "transparent",
    "border": "none",
    "borderBottom": "2px solid",
    "padding": "9px 22px",
    "fontSize": "0.82rem",
    "cursor": "pointer",
    "outline": "none",
    "fontFamily": "inherit",
    "display": "flex",
    "alignItems": "center",
    "gap": "6px",
    "transition": "color 0.15s ease",
}
_TAB_ACTIVE   = {**_TAB_BASE, "color": "#ffffff",  "fontWeight": 700,
                 "borderBottomColor": "#4a90e2"}
_TAB_INACTIVE = {**_TAB_BASE, "color": "#555555",  "fontWeight": 400,
                 "borderBottomColor": "transparent"}


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------

_HINT_STYLE = {"fontSize": "0.68rem", "color": "#666", "marginTop": "-6px", "marginBottom": "8px"}


def _inp(label: str, iid: str, hint: str = "", **kw) -> html.Div:
    """Numeric dcc.Input (type='number') — for small numbers like age, pct."""
    children = [
        html.Div(label, className="threshold-label"),
        dcc.Input(id=iid, style=_NUM_INPUT_STYLE, debounce=False, **kw),
    ]
    if hint:
        children.append(html.Small(hint, style=_HINT_STYLE))
    return html.Div(children)


def _inp_dollar(label: str, iid: str, placeholder: str = "", hint: str = "") -> html.Div:
    """Text dcc.Input with numeric keyboard — for large dollar amounts.

    Using type='text' avoids the browser scroll-wheel-increment bug and
    React controlled-input issues that caused State values to appear as 0.
    """
    children = [
        html.Div(label, className="threshold-label"),
        dcc.Input(
            id=iid,
            type="text",
            inputMode="numeric",
            style=_NUM_INPUT_STYLE,
            debounce=False,
            placeholder=placeholder,
        ),
    ]
    if hint:
        children.append(html.Small(hint, style=_HINT_STYLE))
    return html.Div(children)


def _readiness_class(score: float | None) -> str:
    if score is None:
        return "readiness-score"
    if score >= 0.75:
        return "readiness-score readiness-high"
    if score >= 0.50:
        return "readiness-score readiness-medium"
    return "readiness-score readiness-low"


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

layout = html.Div([
    html.Div([
        html.Span("Retirement ", className="page-title"),
        html.Span("Planner", className="page-title title-accent"),
    ], style={"marginBottom": "20px"}),

    dbc.Row([
        # ── Input sidebar ───────────────────────────────────────────────────
        dbc.Col([
            html.Div(
                style={"overflowY": "auto", "maxHeight": "calc(100vh - 100px)",
                       "paddingRight": "6px"},
                children=[

                    # ── Personal Info ───────────────────────────────────────
                    html.Div("Personal Info", style=_SECTION_STYLE),
                    _inp("Current Age",        "ret-current-age",
                         type="number", value=32,  min=18, max=90),
                    _inp("Retirement Age",     "ret-retirement-age",
                         type="number", value=60,  min=19, max=100),
                    _inp("Life Expectancy",    "ret-life-expectancy",
                         type="number", value=90,  min=50, max=120),

                    # ── Income & Spending ───────────────────────────────────
                    html.Hr(style={"borderColor": "#2a2a2a"}),
                    html.Div("Income & Spending (Controllable)", style=_SECTION_STYLE),
                    _inp_dollar("Annual Salary ($)",              "ret-annual-salary",
                                placeholder="e.g. 100000"),
                    _inp_dollar("Monthly Spending Today ($)",     "ret-monthly-spending",
                                placeholder="e.g. 5000 — enables planning mode"),
                    _inp_dollar("Monthly Taxable Contribution ($)", "ret-monthly-taxable-contrib",
                                placeholder="e.g. 1000"),

                    # ── Current Balances ────────────────────────────────────
                    html.Hr(style={"borderColor": "#2a2a2a"}),
                    html.Div("Current Balances (Uncontrollable)", style=_SECTION_STYLE),
                    _inp_dollar("Taxable Account Balance ($)",   "ret-current-value",
                                placeholder="e.g. 95000"),
                    _inp_dollar("Traditional 401k Balance ($)",  "ret-trad-401k-balance",
                                placeholder="e.g. 0"),
                    _inp_dollar("Roth 401k Balance ($)",         "ret-roth-401k-balance",
                                placeholder="e.g. 0"),
                    _inp_dollar("Roth IRA Balance ($)",          "ret-roth-ira-balance",
                                placeholder="e.g. 0"),

                    # ── Monthly Contributions ───────────────────────────────
                    html.Hr(style={"borderColor": "#2a2a2a"}),
                    html.Div("Monthly Contributions (Controllable)", style=_SECTION_STYLE),
                    _inp_dollar("Monthly Traditional 401k ($)",  "ret-monthly-trad-401k",
                                placeholder="e.g. 500"),
                    _inp_dollar("Monthly Roth 401k ($)",         "ret-monthly-roth-401k",
                                placeholder="e.g. 500"),
                    _inp_dollar("Monthly Roth IRA ($)",          "ret-monthly-roth-ira",
                                placeholder="e.g. 583 (max $7k/yr)",
                                hint="IRS limit: $7,000/yr ($583/mo) in 2024, or $8,000 if age 50+. "
                                     "Contributions are post-tax; qualified withdrawals are tax-free."),
                    _inp("Employer Match Rate (%)",        "ret-employer-match-rate",
                         type="number", value=0, min=0, max=200,
                         placeholder="e.g. 80 = 80% match",
                         hint="Your employer matches this % of each dollar you contribute. "
                              "80% match = $0.80 per $1.00 you put in."),
                    _inp("Employer Match Cap (% of salary)", "ret-employer-match-cap",
                         type="number", value=6, min=0, max=100,
                         placeholder="e.g. 6 = up to 6% of salary",
                         hint="Match only applies to contributions up to this % of your salary. "
                              "e.g. 6% cap on $100k salary = first $6k of your contributions."),

                    # ── Economic Assumptions ────────────────────────────────
                    html.Hr(style={"borderColor": "#2a2a2a"}),
                    html.Div("Economic Assumptions", style=_SECTION_STYLE),
                    _inp("Inflation Rate (%/yr, ~2.5% US 10yr avg)", "ret-inflation",
                         type="number", value=2.5, min=0, max=20),
                    _inp("Post-Retirement Return (%/yr)",  "ret-post-ret-return",
                         type="number", value=5,   min=0, max=30,
                         placeholder="e.g. 5",
                         hint="Expected annual portfolio return after you retire — typically lower "
                              "than pre-retirement as you shift to bonds. 4–6% is a common conservative assumption."),
                    _inp("Contribution Growth / Yr (%)",   "ret-contrib-growth",
                         type="number", value=2.5, min=0, max=20,
                         hint="Rate at which you increase your annual contributions each year, "
                              "e.g. to keep pace with salary raises or inflation."),

                    # ── Tax Rates ───────────────────────────────────────────
                    html.Hr(style={"borderColor": "#2a2a2a"}),
                    html.Div("Tax Rates", style=_SECTION_STYLE),
                    _inp("Ordinary Income Tax Rate (%)",   "ret-ordinary-income-rate",
                         type="number", value=22, min=0, max=60,
                         placeholder="For Trad 401k withdrawals"),
                    _inp("Capital Gains Tax Rate (%)",     "ret-capital-gains-rate",
                         type="number", value=15, min=0, max=40),
                    _inp("Taxable Cost Basis Ratio (%)",   "ret-cost-basis-ratio",
                         type="number", value=50, min=0, max=100,
                         placeholder="% of taxable FV that is basis",
                         hint="% of your taxable account's current value that is original cost "
                              "(the rest is unrealised gain taxed at the capital gains rate on withdrawal). "
                              "50% means half of the balance is gain."),

                    # ── Simulation Mode ─────────────────────────────────────
                    html.Hr(style={"borderColor": "#2a2a2a"}),
                    html.Div("Simulation Mode", style=_SECTION_STYLE),
                    dbc.RadioItems(
                        id="ret-sim-mode",
                        options=[
                            {"label": "Fast (cached randoms)", "value": "fast"},
                            {"label": "True Random",            "value": "random"},
                        ],
                        value="fast",
                        inline=False,
                        style={"fontSize": "0.80rem", "color": "#ccc",
                               "marginBottom": "8px"},
                        input_style={"marginRight": "6px"},
                    ),
                    html.Div(
                        "Fast: reproducible, ~instant.  True Random: fresh each run.",
                        style={"color": "#666", "fontSize": "0.65rem",
                               "marginBottom": "10px"},
                    ),

                    # ── Action buttons ──────────────────────────────────────
                    dbc.Button(
                        [html.I(className="bi-clipboard-data me-2"),
                         "Generate Planning Summary"],
                        id="ret-plan-btn",
                        color="success",
                        style={"width": "100%", "marginBottom": "8px"},
                        n_clicks=0,
                    ),
                    dbc.Button(
                        [html.I(className="bi-graph-up me-2"),
                         "Run Monte Carlo Simulation"],
                        id="ret-mc-btn",
                        color="primary",
                        style={"width": "100%"},
                        n_clicks=0,
                    ),
                    html.Div(
                        "Planning Summary is fast (~instant). "
                        "Monte Carlo runs 3 scenarios (~1–5s).",
                        style={"color": "#666", "fontSize": "0.68rem",
                               "marginTop": "6px", "textAlign": "center"},
                    ),

                    # ── Saved Scenarios ─────────────────────────────────────
                    html.Hr(style={"borderColor": "#2a2a2a"}),
                    html.Div("Saved Scenarios", style=_SECTION_STYLE),
                    html.Div(id="ret-save-status",
                             style={"fontSize": "0.70rem", "minHeight": "18px",
                                    "marginBottom": "4px"}),
                    dbc.InputGroup([
                        dbc.Input(
                            id="ret-profile-name",
                            placeholder="Scenario name…",
                            style={"backgroundColor": "#111111", "color": "#ffffff",
                                   "border": "1px solid #2a2a2a", "fontSize": "0.80rem"},
                        ),
                        dbc.Button("Save", id="ret-save-profile-btn",
                                   color="success", outline=True, size="sm", n_clicks=0),
                    ], size="sm", className="mb-2"),
                    dcc.Dropdown(
                        id="ret-profile-select",
                        placeholder="Load a saved scenario…",
                        options=[],
                        style={"backgroundColor": "#1a1a1a", "fontSize": "0.80rem",
                               "marginBottom": "8px"},
                        clearable=True,
                    ),
                    dbc.Row([
                        dbc.Col(
                            dbc.Button("Load", id="ret-load-profile-btn",
                                       color="primary", outline=True, size="sm",
                                       style={"width": "100%"}, n_clicks=0),
                            width=6,
                        ),
                        dbc.Col(
                            dbc.Button("Delete", id="ret-delete-profile-btn",
                                       color="danger", outline=True, size="sm",
                                       style={"width": "100%"}, n_clicks=0),
                            width=6,
                        ),
                    ], className="g-1"),
                ],
            ),
        ], md=3, style={"backgroundColor": "#111111", "padding": "20px",
                        "borderRight": "1px solid #2a2a2a"}),

        # ── Results panel ───────────────────────────────────────────────────
        dbc.Col([
            dcc.Store(id="ret-active-tab", data="all"),

            # ── Tab bar ──────────────────────────────────────────────────────
            html.Div([
                html.Button(
                    [html.I(className="bi-grid-1x2 me-1"), "All Results"],
                    id="ret-tab-all", n_clicks=0,
                    style=_TAB_ACTIVE,
                ),
                html.Button(
                    [html.I(className="bi-clipboard-data me-1"), "Planning Summary"],
                    id="ret-tab-plan", n_clicks=0,
                    style=_TAB_INACTIVE,
                ),
                html.Button(
                    [html.I(className="bi-graph-up me-1"), "Monte Carlo"],
                    id="ret-tab-mc", n_clicks=0,
                    style=_TAB_INACTIVE,
                ),
            ], style={
                "display": "flex", "gap": "0",
                "borderBottom": "1px solid #2a2a2a",
                "marginBottom": "22px",
            }),

            # ── Planning results wrapper ──────────────────────────────────────
            html.Div([
                dcc.Loading(
                    html.Div(id="ret-planning-results", style={"minHeight": "60px"}),
                    type="circle", color="#2ecc71",
                    style={"minHeight": "60px"},
                ),
            ], id="ret-wrap-planning"),

            # ── MC results wrapper ────────────────────────────────────────────
            html.Div([
                dcc.Loading(
                    html.Div(id="ret-mc-results", style={"minHeight": "60px"}),
                    type="circle", color="#4a90e2",
                    style={"minHeight": "60px"},
                ),
            ], id="ret-wrap-mc"),

        ], md=9, style={"padding": "20px"}),
    ], className="g-0"),
])


# ---------------------------------------------------------------------------
# Tab switching callbacks
# ---------------------------------------------------------------------------

@callback(
    Output("ret-active-tab", "data"),
    Input("ret-tab-all",  "n_clicks"),
    Input("ret-tab-plan", "n_clicks"),
    Input("ret-tab-mc",   "n_clicks"),
    prevent_initial_call=True,
)
def _set_tab(*_):
    mapping = {"ret-tab-all": "all", "ret-tab-plan": "plan", "ret-tab-mc": "mc"}
    return mapping.get(ctx.triggered_id, "all")


@callback(
    Output("ret-wrap-planning", "style"),
    Output("ret-wrap-mc",       "style"),
    Output("ret-tab-all",       "style"),
    Output("ret-tab-plan",      "style"),
    Output("ret-tab-mc",        "style"),
    Input("ret-active-tab", "data"),
)
def _apply_tab(tab):
    show, hide = {}, {"display": "none"}
    a, i = _TAB_ACTIVE, _TAB_INACTIVE
    if tab == "plan":
        return show, hide, i, a, i
    if tab == "mc":
        return hide, show, i, i, a
    return show, show, a, i, i   # "all" (default)


# ---------------------------------------------------------------------------
# Helpers: coerce raw input values (text or number) to Python types
# ---------------------------------------------------------------------------

def _f(v, default: float = 0.0) -> float:
    """Parse a value from dcc.Input (text or number) to float."""
    if v in (None, "", "None"):
        return default
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return default


def _i(v, default: int = 0) -> int:
    """Parse a value from dcc.Input (text or number) to int."""
    if v in (None, "", "None"):
        return default
    try:
        return int(float(str(v).replace(",", "").strip()))
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Shared: all form States (for both callbacks)
# ---------------------------------------------------------------------------

# (component_id, snapshot_key, default_value) — single source of truth for all form fields.
_FORM_FIELDS: list[tuple[str, str, object]] = [
    ("ret-current-age",             "current_age",             32),
    ("ret-retirement-age",          "retirement_age",          60),
    ("ret-life-expectancy",         "life_expectancy",         90),
    ("ret-annual-salary",           "annual_salary",            0),
    ("ret-monthly-spending",        "monthly_spending",         0),
    ("ret-monthly-taxable-contrib", "monthly_taxable_contrib",  0),
    ("ret-current-value",           "current_value",            0),
    ("ret-trad-401k-balance",       "trad_401k_balance",        0),
    ("ret-roth-401k-balance",       "roth_401k_balance",        0),
    ("ret-roth-ira-balance",        "roth_ira_balance",         0),
    ("ret-monthly-trad-401k",       "monthly_trad_401k",        0),
    ("ret-monthly-roth-401k",       "monthly_roth_401k",        0),
    ("ret-monthly-roth-ira",        "monthly_roth_ira",         0),
    ("ret-employer-match-rate",     "employer_match_rate",      0),
    ("ret-employer-match-cap",      "employer_match_cap",       6),
    ("ret-inflation",               "inflation",              2.5),
    ("ret-post-ret-return",         "post_ret_return",          5),
    ("ret-contrib-growth",          "contrib_growth",         2.5),
    ("ret-ordinary-income-rate",    "ordinary_income_rate",    22),
    ("ret-capital-gains-rate",      "capital_gains_rate",      15),
    ("ret-cost-basis-ratio",        "cost_basis_ratio",        50),
    ("ret-sim-mode",                "sim_mode",            "fast"),
]
_DEFAULTS     = {key: dflt for _, key, dflt in _FORM_FIELDS}
_ALL_STATES   = [State(cid, "value") for cid, _, _ in _FORM_FIELDS]
_ALL_INPUTS   = [Input(cid,  "value") for cid, _, _ in _FORM_FIELDS]
_SNAPSHOT_KEYS = [key for _, key, _ in _FORM_FIELDS]


def _coerce_inputs(
    current_age, retirement_age, life_expectancy,
    annual_salary, monthly_spending, monthly_taxable_contrib,
    current_value, trad_401k_balance, roth_401k_balance, roth_ira_balance,
    monthly_trad_401k, monthly_roth_401k, monthly_roth_ira,
    employer_match_rate_pct, employer_match_cap_pct,
    inflation, post_ret_return, contrib_growth,
    ordinary_income_rate_pct, capital_gains_rate_pct, cost_basis_ratio_pct,
):
    """Return a dict of coerced numeric values from raw form inputs."""
    return {
        "current_age":             _i(current_age,             32),
        "retirement_age":          _i(retirement_age,          60),
        "life_expectancy":         _i(life_expectancy,         90),
        "annual_salary":           _f(annual_salary,           0.0),
        "monthly_spending":        _f(monthly_spending,        0.0),
        "monthly_taxable_contrib": _f(monthly_taxable_contrib, 0.0),
        "current_value":           _f(current_value,           0.0),
        "trad_401k_balance":       _f(trad_401k_balance,       0.0),
        "roth_401k_balance":       _f(roth_401k_balance,       0.0),
        "roth_ira_balance":        _f(roth_ira_balance,        0.0),
        "monthly_trad_401k":       _f(monthly_trad_401k,       0.0),
        "monthly_roth_401k":       _f(monthly_roth_401k,       0.0),
        "monthly_roth_ira":        _f(monthly_roth_ira,        0.0),
        "employer_match_rate_pct": _f(employer_match_rate_pct, 0.0),
        "employer_match_cap_pct":  _f(employer_match_cap_pct,  6.0),
        "inflation":               _f(inflation,               2.5),
        "post_ret_return":         _f(post_ret_return,         5.0),
        "contrib_growth":          _f(contrib_growth,          2.5),
        "ordinary_income_rate_pct":_f(ordinary_income_rate_pct,22.0),
        "capital_gains_rate_pct":  _f(capital_gains_rate_pct,  15.0),
        "cost_basis_ratio_pct":    _f(cost_basis_ratio_pct,    50.0),
    }


# ---------------------------------------------------------------------------
# Combined callback: plan button + MC button → two result divs + store
# ---------------------------------------------------------------------------

@callback(
    Output("ret-planning-results", "children"),
    Output("ret-mc-results",       "children"),
    Output("ret-form-store",       "data", allow_duplicate=True),
    Input("ret-plan-btn", "n_clicks"),
    Input("ret-mc-btn",   "n_clicks"),
    *_ALL_STATES,
    prevent_initial_call=True,
)
def run_analysis(
    _plan_clicks, _mc_clicks,
    current_age, retirement_age, life_expectancy,
    annual_salary, monthly_spending, monthly_taxable_contrib,
    current_value, trad_401k_balance, roth_401k_balance, roth_ira_balance,
    monthly_trad_401k, monthly_roth_401k, monthly_roth_ira,
    employer_match_rate_pct, employer_match_cap_pct,
    inflation, post_ret_return, contrib_growth,
    ordinary_income_rate_pct, capital_gains_rate_pct, cost_basis_ratio_pct,
    sim_mode,
):
    triggered = ctx.triggered_id
    if triggered not in ("ret-plan-btn", "ret-mc-btn"):
        raise PreventUpdate

    v = _coerce_inputs(
        current_age, retirement_age, life_expectancy,
        annual_salary, monthly_spending, monthly_taxable_contrib,
        current_value, trad_401k_balance, roth_401k_balance, roth_ira_balance,
        monthly_trad_401k, monthly_roth_401k, monthly_roth_ira,
        employer_match_rate_pct, employer_match_cap_pct,
        inflation, post_ret_return, contrib_growth,
        ordinary_income_rate_pct, capital_gains_rate_pct, cost_basis_ratio_pct,
    )

    # Build snapshot for localStorage (raw values as-typed, not coerced)
    snapshot = {
        "current_age":             current_age,
        "retirement_age":          retirement_age,
        "life_expectancy":         life_expectancy,
        "annual_salary":           annual_salary,
        "monthly_spending":        monthly_spending,
        "monthly_taxable_contrib": monthly_taxable_contrib,
        "current_value":           current_value,
        "trad_401k_balance":       trad_401k_balance,
        "roth_401k_balance":       roth_401k_balance,
        "roth_ira_balance":        roth_ira_balance,
        "monthly_trad_401k":       monthly_trad_401k,
        "monthly_roth_401k":       monthly_roth_401k,
        "monthly_roth_ira":        monthly_roth_ira,
        "employer_match_rate":     employer_match_rate_pct,
        "employer_match_cap":      employer_match_cap_pct,
        "inflation":               inflation,
        "post_ret_return":         post_ret_return,
        "contrib_growth":          contrib_growth,
        "ordinary_income_rate":    ordinary_income_rate_pct,
        "capital_gains_rate":      capital_gains_rate_pct,
        "cost_basis_ratio":        cost_basis_ratio_pct,
        "sim_mode":                sim_mode,
    }

    # Basic validation
    if not v["current_value"] or not v["current_age"] or not v["retirement_age"]:
        err = dbc.Alert(
            "Please fill in Current Age, Retirement Age, and Taxable Account Balance.",
            color="warning",
        )
        return err, no_update, snapshot
    if v["retirement_age"] <= v["current_age"]:
        err = dbc.Alert("Retirement age must be greater than current age.", color="danger")
        return err, no_update, snapshot

    # Normalise pct → decimal
    inflation_rate  = v["inflation"]               / 100
    contrib_growth  = v["contrib_growth"]          / 100
    post_ret_rate   = v["post_ret_return"]         / 100
    match_rate      = v["employer_match_rate_pct"] / 100
    match_cap       = v["employer_match_cap_pct"]  / 100
    oi_rate         = v["ordinary_income_rate_pct"] / 100
    cg_rate         = v["capital_gains_rate_pct"]  / 100
    cb_ratio        = v["cost_basis_ratio_pct"]    / 100
    monthly_taxable = v["monthly_taxable_contrib"]

    run_mc = (triggered == "ret-mc-btn")

    try:
        result = run_retirement(
            current_value=v["current_value"],
            current_age=v["current_age"],
            retirement_age=v["retirement_age"],
            annual_contribution=monthly_taxable * 12,
            contribution_growth_rate=contrib_growth,
            inflation_rate=inflation_rate,
            monthly_spending=v["monthly_spending"],
            life_expectancy=v["life_expectancy"],
            monthly_taxable_contribution=monthly_taxable,
            trad_401k_balance=v["trad_401k_balance"],
            roth_401k_balance=v["roth_401k_balance"],
            roth_ira_balance=v["roth_ira_balance"],
            monthly_trad_401k=v["monthly_trad_401k"],
            monthly_roth_401k=v["monthly_roth_401k"],
            monthly_roth_ira=v["monthly_roth_ira"],
            employer_match_rate=match_rate,
            employer_match_cap=match_cap,
            annual_salary=v["annual_salary"],
            ordinary_income_rate=oi_rate,
            capital_gains_rate=cg_rate,
            cost_basis_ratio=cb_ratio,
            post_retirement_return=post_ret_rate,
            use_cached_randoms=((sim_mode or "fast") == "fast"),
            run_mc=run_mc,
        )
    except Exception as exc:
        err = dbc.Alert(f"API call failed: {exc}", color="danger",
                        style={"fontFamily": "monospace", "fontSize": "0.80rem"})
        return err, no_update, snapshot

    if not result:
        err = dbc.Alert("API unavailable or projection failed.", color="danger")
        return err, no_update, snapshot

    planning   = result.get("planning")
    scenarios  = result.get("scenarios", {})
    horizon    = result.get("horizon_years", 0)
    total_port = result.get("total_portfolio_value", v["current_value"])

    # ── Planning summary (always generated) ──────────────────────────────────
    planning_ui = _build_planning_ui(
        v=v,
        planning=planning,
        total_port=total_port,
        inflation_rate=inflation_rate,
        post_ret_rate=post_ret_rate,
        contrib_growth=contrib_growth,
        match_rate=match_rate,
        match_cap=match_cap,
        oi_rate=oi_rate,
        cg_rate=cg_rate,
        cb_ratio=cb_ratio,
        monthly_taxable=monthly_taxable,
        sim_mode=(sim_mode or "fast"),
    )

    if run_mc:
        mc_ui = _build_mc_ui(scenarios, horizon, total_port, planning)
        return planning_ui, mc_ui, snapshot
    else:
        return planning_ui, no_update, snapshot


# ---------------------------------------------------------------------------
# Form persistence: restore inputs from localStorage on navigation
# ---------------------------------------------------------------------------

@callback(
    *[Output(cid, "value", allow_duplicate=True) for cid, _, _ in _FORM_FIELDS],
    Output("ret-profile-select", "options"),
    Input("url", "pathname"),
    State("ret-form-store",     "data"),
    State("ret-profiles-store", "data"),
    prevent_initial_call="initial_duplicate",
)
def restore_form(pathname, stored, profiles):
    """Re-populate the form from localStorage when navigating to /retirement."""
    if pathname != "/retirement":
        raise PreventUpdate
    snap = stored or {}
    values = tuple(snap.get(key, dflt) for _, key, dflt in _FORM_FIELDS)
    opts   = [{"label": k, "value": k} for k in sorted(profiles or {})]
    return (*values, opts)


# ---------------------------------------------------------------------------
# Auto-save: persist form to localStorage on every input change
# ---------------------------------------------------------------------------

@callback(
    Output("ret-form-store",  "data",     allow_duplicate=True),
    Output("ret-save-status", "children", allow_duplicate=True),
    *_ALL_INPUTS,
    prevent_initial_call=True,
)
def autosave_form(*values):
    snapshot = dict(zip(_SNAPSHOT_KEYS, values))
    status   = html.Span("✓ Auto-saved", style={"color": "#555", "fontSize": "0.68rem"})
    return snapshot, status


# ---------------------------------------------------------------------------
# Profiles: save / load / delete named scenarios
# ---------------------------------------------------------------------------

@callback(
    Output("ret-profiles-store",    "data"),
    Output("ret-profile-select",    "options",  allow_duplicate=True),
    Output("ret-save-status",       "children", allow_duplicate=True),
    Input("ret-save-profile-btn",   "n_clicks"),
    State("ret-profile-name",       "value"),
    State("ret-profiles-store",     "data"),
    *_ALL_STATES,
    prevent_initial_call=True,
)
def save_profile(n, name, profiles, *values):
    if not n:
        raise PreventUpdate
    name = (name or "").strip()
    if not name:
        return (no_update, no_update,
                dbc.Alert("Enter a scenario name first.", color="warning",
                          style={"padding": "4px 10px", "fontSize": "0.72rem",
                                 "marginBottom": 0}))
    profiles = dict(profiles or {})
    profiles[name] = dict(zip(_SNAPSHOT_KEYS, values))
    opts   = [{"label": k, "value": k} for k in sorted(profiles)]
    status = html.Span(f'✓ Saved "{name}"',
                       style={"color": "#2ecc71", "fontSize": "0.70rem"})
    return profiles, opts, status


@callback(
    *[Output(cid, "value", allow_duplicate=True) for cid, _, _ in _FORM_FIELDS],
    Output("ret-save-status", "children", allow_duplicate=True),
    Input("ret-load-profile-btn", "n_clicks"),
    State("ret-profile-select",   "value"),
    State("ret-profiles-store",   "data"),
    prevent_initial_call=True,
)
def load_profile(n, selected, profiles):
    if not n or not selected or not profiles or selected not in profiles:
        raise PreventUpdate
    snap   = profiles[selected]
    values = tuple(snap.get(key, dflt) for _, key, dflt in _FORM_FIELDS)
    status = html.Span(f'✓ Loaded "{selected}"',
                       style={"color": "#4a90e2", "fontSize": "0.70rem"})
    return (*values, status)


@callback(
    Output("ret-profiles-store",    "data",     allow_duplicate=True),
    Output("ret-profile-select",    "options",  allow_duplicate=True),
    Output("ret-profile-select",    "value"),
    Output("ret-save-status",       "children", allow_duplicate=True),
    Input("ret-delete-profile-btn", "n_clicks"),
    State("ret-profile-select",     "value"),
    State("ret-profiles-store",     "data"),
    prevent_initial_call=True,
)
def delete_profile(n, selected, profiles):
    if not n or not selected or not profiles or selected not in profiles:
        raise PreventUpdate
    profiles = dict(profiles)
    del profiles[selected]
    opts   = [{"label": k, "value": k} for k in sorted(profiles)]
    status = html.Span(f'✓ Deleted "{selected}"',
                       style={"color": "#e74c3c", "fontSize": "0.70rem"})
    return profiles, opts, None, status


# ---------------------------------------------------------------------------
# UI builder helpers
# ---------------------------------------------------------------------------

_CARD_BOX = {
    "backgroundColor": "#111111",
    "border": "1px solid #2a2a2a",
    "borderRadius": "6px",
    "padding": "16px 18px",
    "height": "100%",
}


def _kpi_card(
    title: str,
    value_str: str,
    value_color: str,
    description: str,
    badge_text: str | None = None,
    badge_color: str | None = None,
    extra_content=None,
    icon: str = "",
) -> html.Div:
    """Styled KPI card with title, value, optional badge, description."""
    header = html.Div([
        html.I(className=f"{icon} me-1",
               style={"color": "#555", "fontSize": "0.78rem"}) if icon else None,
        html.Span(title, style={
            "color": "#777", "fontSize": "0.68rem",
            "textTransform": "uppercase", "letterSpacing": "0.07em",
            "fontWeight": 600,
        }),
    ], style={"display": "flex", "alignItems": "center", "marginBottom": "8px"})

    value = html.Div(value_str, style={
        "fontSize": "1.55rem", "fontWeight": 800,
        "color": value_color, "lineHeight": "1.1", "marginBottom": "4px",
    })

    children = [header, value]
    if badge_text and badge_color:
        children.append(html.Span(badge_text, style={
            "fontSize": "0.62rem", "fontWeight": 700,
            "letterSpacing": "0.09em", "color": badge_color,
            "backgroundColor": f"{badge_color}22",
            "padding": "2px 9px", "borderRadius": "10px",
            "display": "inline-block", "marginBottom": "6px",
        }))
    if extra_content:
        children.append(extra_content)
    children.append(html.Div(description, style={
        "fontSize": "0.71rem", "color": "#aaaaaa", "lineHeight": "1.55",
        "marginTop": "8px",
    }))
    return html.Div(children, style=_CARD_BOX)


def _return_rate_meter(req_rate_pct: float, rate_color: str) -> html.Div:
    """Horizontal fill bar: 0–15% scale, coloured by risk level."""
    fill_pct = min(req_rate_pct / 15 * 100, 100)
    return html.Div([
        html.Div([
            html.Div(style={
                "width": f"{fill_pct:.1f}%", "height": "100%",
                "backgroundColor": rate_color, "borderRadius": "3px",
                "opacity": 0.80,
            }),
        ], style={
            "width": "100%", "height": "6px", "backgroundColor": "#1e1e1e",
            "borderRadius": "3px", "marginTop": "10px", "marginBottom": "5px",
        }),
        html.Div([
            html.Span("0%", style={"color": "#2ecc71", "fontSize": "0.60rem"}),
            html.Span("6% safe", style={"color": "#2ecc71", "fontSize": "0.60rem"}),
            html.Span("10%",     style={"color": "#f39c12", "fontSize": "0.60rem"}),
            html.Span("15%+",   style={"color": "#e74c3c", "fontSize": "0.60rem"}),
        ], style={"display": "flex", "justifyContent": "space-between"}),
    ])


def _assumption_chip(label: str, value: str) -> html.Div:
    return html.Div([
        html.Span(f"{label}:  ", style={"color": "#888", "fontSize": "0.71rem"}),
        html.Span(value, style={"color": "#dddddd", "fontSize": "0.71rem", "fontWeight": 600}),
    ], style={"marginBottom": "5px"})


def _raw_summary_details(summary_text: str) -> html.Details:
    """Collapsible raw bilingual text — no JS callback needed (native HTML5)."""
    return html.Details([
        html.Summary(
            "▸  Raw Input Parameters & Bilingual Summary  (click to expand)",
            style={"cursor": "pointer", "color": "#666666", "fontSize": "0.71rem",
                   "userSelect": "none", "listStyle": "none",
                   "padding": "6px 0"},
        ),
        html.Pre(summary_text, style={
            "backgroundColor": "#080808",
            "color": "#2e6a2e",
            "fontFamily": "'Courier New', 'Consolas', monospace",
            "fontSize": "0.68rem", "lineHeight": "1.55",
            "padding": "14px 16px", "borderRadius": "4px",
            "border": "1px solid #162016",
            "overflowX": "auto", "whiteSpace": "pre",
            "marginTop": "8px",
        }),
    ], style={"marginTop": "16px", "borderTop": "1px solid #1a1a1a",
              "paddingTop": "8px"})


# ---------------------------------------------------------------------------
# UI builder: Planning Summary section
# ---------------------------------------------------------------------------

def _build_planning_ui(
    v: dict,
    planning: dict | None,
    total_port: float,
    inflation_rate: float,
    post_ret_rate: float,
    contrib_growth: float,
    match_rate: float,
    match_cap: float,
    oi_rate: float,
    cg_rate: float,
    cb_ratio: float,
    monthly_taxable: float,
    sim_mode: str,
) -> html.Div:

    horizon             = v["retirement_age"] - v["current_age"]
    years_in_retirement = v["life_expectancy"] - v["retirement_age"]

    summary_text = _format_summary(
        v, planning, total_port,
        inflation_rate, post_ret_rate, contrib_growth,
        match_rate, match_cap, oi_rate, cg_rate, cb_ratio,
        monthly_taxable, sim_mode,
    )

    # ── No monthly spending set → portfolio snapshot only ─────────────────────
    if not planning:
        return html.Div([
            html.Div("Planning Summary", className="section-title",
                     style={"marginBottom": "16px"}),
            dbc.Row([
                dbc.Col(_kpi_card(
                    "Total Portfolio Today", f"${total_port:,.0f}", "#4a90e2",
                    "Combined current value of all your investment accounts "
                    "(taxable + 401k + IRA).",
                    icon="bi-wallet2",
                ), md=4),
                dbc.Col(_kpi_card(
                    "Years to Retirement", str(horizon), "#f39c12",
                    f"From age {v['current_age']} today to your target retirement "
                    f"at age {v['retirement_age']}.",
                    icon="bi-calendar-event",
                ), md=4),
                dbc.Col(_kpi_card(
                    "Retirement Duration", f"{years_in_retirement} yrs", "#a29af0",
                    f"From retirement at {v['retirement_age']} to life expectancy at "
                    f"{v['life_expectancy']} — the span your savings must cover.",
                    icon="bi-hourglass-split",
                ), md=4),
            ], className="g-3 mb-3"),
            dbc.Alert([
                html.I(className="bi-info-circle me-2"),
                "Enter ", html.Strong("Monthly Spending Today"),
                " to unlock the full planning analysis — nest egg target, "
                "required return rate, and goal status.",
            ], color="info", style={"fontSize": "0.82rem"}),
            _raw_summary_details(summary_text),
        ])

    # ── Extract planning results ──────────────────────────────────────────────
    req_rate_pct = planning["required_return_rate"] * 100
    nest_egg     = planning["required_nest_egg"]
    monthly_ret  = planning["monthly_spending_at_retirement"]
    fv_tax       = planning["fv_taxable"]
    fv_trad      = planning["fv_trad_401k"]
    fv_roth      = planning["fv_roth_401k"]
    fv_roth_ira  = planning.get("fv_roth_ira", 0.0)
    at_total     = planning["after_tax_total"]
    eff_trad     = planning["eff_monthly_trad"]
    eff_roth     = planning["eff_monthly_roth"]
    eff_match    = planning["eff_monthly_match"]
    eff_roth_ira = planning.get("eff_monthly_roth_ira", 0.0)
    total_401k   = eff_trad + eff_roth + eff_match

    at_taxable = fv_tax - fv_tax * (1 - cb_ratio) * cg_rate
    at_trad    = fv_trad * (1 - oi_rate)
    shortfall  = at_total - nest_egg

    # ── Goal status: colour + label (same text as before, just coloured) ──────
    goal_str = (
        f"달성 가능 / Met  (Surplus: ${shortfall:+,.0f})"
        if shortfall >= 0
        else f"부족 / Shortfall: ${shortfall:,.0f}"
    )
    surplus_ratio = shortfall / max(nest_egg, 1)
    if shortfall < 0:
        g_color, g_bg, g_border = "#e74c3c", "rgba(231,76,60,0.07)", "#4a1818"
        g_icon, g_tag = "bi-x-circle-fill", "HARD"
        g_desc = (
            "Your projected savings fall short of your retirement goal. "
            "Consider saving more, retiring later, or spending less."
        )
    elif surplus_ratio < 0.15:
        g_color, g_bg, g_border = "#f39c12", "rgba(243,156,18,0.07)", "#4a3010"
        g_icon, g_tag = "bi-dash-circle-fill", "MAYBE"
        g_desc = (
            "You're close to your goal but the margin is thin — "
            "a single bad market year could tip it. A small boost now goes a long way."
        )
    else:
        g_color, g_bg, g_border = "#2ecc71", "rgba(46,204,113,0.07)", "#1a4228"
        g_icon, g_tag = "bi-check-circle-fill", "SAFE"
        g_desc = (
            "You're on track with a comfortable cushion above your retirement goal. "
            "Keep your current strategy and review periodically."
        )

    goal_banner = html.Div([
        html.Div([
            html.I(className=f"{g_icon} me-2",
                   style={"fontSize": "1.25rem", "color": g_color,
                          "flexShrink": 0}),
            html.Div([
                html.Div([
                    html.Span(g_tag, style={
                        "fontWeight": 800, "fontSize": "0.70rem",
                        "color": g_color, "letterSpacing": "0.14em",
                        "backgroundColor": f"{g_color}22",
                        "padding": "2px 10px", "borderRadius": "12px",
                        "marginRight": "10px",
                    }),
                    html.Span(goal_str, style={
                        "fontSize": "0.98rem", "fontWeight": 700,
                        "color": g_color,
                    }),
                ], style={"display": "flex", "alignItems": "center",
                          "marginBottom": "4px"}),
                html.Div(g_desc, style={
                    "fontSize": "0.72rem", "color": "#aaaaaa", "lineHeight": "1.4",
                }),
            ]),
        ], style={"display": "flex", "alignItems": "flex-start", "gap": "12px"}),
    ], style={
        "backgroundColor": g_bg,
        "border": f"1px solid {g_border}",
        "borderLeft": f"4px solid {g_color}",
        "borderRadius": "6px",
        "padding": "14px 18px",
        "marginBottom": "20px",
    })

    # ── Required return rate visuals ──────────────────────────────────────────
    if req_rate_pct <= 6:
        r_color, r_verdict, r_tag = "#2ecc71", "Achievable",            "LOW RISK"
    elif req_rate_pct <= 10:
        r_color, r_verdict, r_tag = "#f39c12", "Stretch Goal",          "MODERATE RISK"
    else:
        r_color, r_verdict, r_tag = "#e74c3c", "Aggressive / High Risk","HIGH RISK"

    # ── KPI row: What You Need ────────────────────────────────────────────────
    kpi_row = dbc.Row([
        dbc.Col(_kpi_card(
            "Required Nest Egg",
            f"${nest_egg:,.0f}",
            "#4a90e2",
            f"The total savings you need at retirement so that — assuming your "
            f"portfolio earns {post_ret_rate*100:.1f}%/yr — you can keep spending "
            f"${v['monthly_spending']:,.0f}/mo (today's dollars, inflation-adjusted) "
            f"for all {years_in_retirement} years of retirement without running out of money.",
            icon="bi-bullseye",
        ), md=4),
        dbc.Col(_kpi_card(
            "Required Annual Return",
            f"{req_rate_pct:.2f}%",
            r_color,
            f"The average yearly return your entire portfolio must earn over the next "
            f"{horizon} years to grow to your ${nest_egg:,.0f} nest egg. "
            f"Think of it as the 'hurdle rate' your investments need to clear every year. "
            f"Historically, a diversified stock portfolio returns ~7–10%/yr before inflation.",
            badge_text=r_tag,
            badge_color=r_color,
            extra_content=_return_rate_meter(req_rate_pct, r_color),
            icon="bi-graph-up-arrow",
        ), md=4),
        dbc.Col(_kpi_card(
            "Monthly Budget at Retirement",
            f"${monthly_ret:,.0f}/mo",
            "#f39c12",
            f"Your current ${v['monthly_spending']:,.0f}/mo lifestyle, inflated at "
            f"{inflation_rate*100:.1f}%/yr over {horizon} years — this is what the same "
            f"standard of living will actually cost in future dollars when you retire at {v['retirement_age']}.",
            icon="bi-calendar-month",
        ), md=4),
    ], className="g-3 mb-4")

    # ── Funding progress bar ──────────────────────────────────────────────────
    funded_pct = (at_total / max(nest_egg, 1)) * 100
    bar_fill   = min(funded_pct, 100)

    progress_block = html.Div([
        html.Div([
            html.I(className="bi-bar-chart-fill me-2",
                   style={"color": "#4a90e2", "fontSize": "0.85rem"}),
            html.Span("Projected Portfolio vs Goal",
                      style={"fontWeight": 700, "fontSize": "0.80rem",
                             "color": "#cccccc"}),
        ], style={"display": "flex", "alignItems": "center",
                  "marginBottom": "14px"}),
        # Amount + percentage
        html.Div([
            html.Span("Your After-Tax Total  ",
                      style={"color": "#aaaaaa", "fontSize": "0.72rem"}),
            html.Span(f"${at_total:,.0f}",
                      style={"fontSize": "1.35rem", "fontWeight": 800,
                             "color": g_color, "marginRight": "10px"}),
            html.Span(f"({funded_pct:.0f}% funded)",
                      style={"color": g_color, "fontSize": "0.80rem",
                             "fontWeight": 600}),
        ], style={"marginBottom": "10px"}),
        # Progress bar
        html.Div([
            html.Div(style={
                "width": f"{bar_fill:.1f}%", "height": "100%",
                "backgroundColor": g_color, "borderRadius": "6px",
            }),
        ], style={
            "width": "100%", "height": "12px",
            "backgroundColor": "#1e1e1e", "borderRadius": "6px",
            "marginBottom": "5px",
        }),
        html.Div([
            html.Span("$0", style={"color": "#777777", "fontSize": "0.65rem"}),
            html.Span(f"Goal: ${nest_egg:,.0f}",
                      style={"color": "#777777", "fontSize": "0.65rem"}),
        ], style={"display": "flex", "justifyContent": "space-between",
                  "marginBottom": "10px"}),
        html.Div(
            "What your combined accounts are projected to be worth after paying "
            "all applicable taxes at retirement — the amount you'll actually be able to spend.",
            style={"fontSize": "0.70rem", "color": "#999999", "lineHeight": "1.5"},
        ),
    ], style={**_CARD_BOX, "marginBottom": "20px"})

    # ── Account breakdown table ───────────────────────────────────────────────
    _th = lambda t: html.Th(t, style={
        "color": "#555", "fontWeight": 600, "fontSize": "0.68rem",
        "textTransform": "uppercase", "letterSpacing": "0.05em",
        "borderBottom": "1px solid #2a2a2a", "paddingBottom": "8px",
    })

    def _acct_row(icon_cls, name, fv, at_val, contrib_cell, tax_free=False):
        at_color = "#2ecc71" if tax_free else "#cccccc"
        return html.Tr([
            html.Td(html.Span([
                html.I(className=f"{icon_cls} me-1",
                       style={"color": "#555", "fontSize": "0.75rem"}),
                name,
            ]), style={"color": "#bbb", "fontSize": "0.83rem",
                       "paddingTop": "10px"}),
            html.Td(f"${fv:,.0f}",
                    style={"textAlign": "right", "color": "#666",
                           "fontSize": "0.83rem", "paddingTop": "10px"}),
            html.Td(f"${at_val:,.0f}",
                    style={"textAlign": "right", "color": at_color,
                           "fontWeight": 600, "fontSize": "0.83rem",
                           "paddingTop": "10px"}),
            html.Td(contrib_cell,
                    style={"textAlign": "right", "paddingTop": "10px"}),
        ])

    rows = [
        _acct_row(
            "bi-graph-up", "Taxable Account",
            fv_tax, at_taxable,
            html.Span(f"${monthly_taxable:,.0f}/mo",
                      style={"color": "#777", "fontSize": "0.80rem"}),
        ),
        _acct_row(
            "bi-building", "Traditional 401k",
            fv_trad, at_trad,
            html.Div([
                html.Span(f"${eff_trad:,.0f}/mo",
                          style={"color": "#777", "fontSize": "0.80rem"}),
                html.Span(f"  +${eff_match:,.0f} match",
                          style={"color": "#2ecc71", "fontSize": "0.73rem"}),
            ]),
        ),
        _acct_row(
            "bi-shield-check", "Roth 401k",
            fv_roth, fv_roth,
            html.Span(f"${eff_roth:,.0f}/mo",
                      style={"color": "#777", "fontSize": "0.80rem"}),
            tax_free=True,
        ),
        _acct_row(
            "bi-piggy-bank", "Roth IRA",
            fv_roth_ira, fv_roth_ira,
            html.Span(f"${eff_roth_ira:,.0f}/mo",
                      style={"color": "#777", "fontSize": "0.80rem"}),
            tax_free=True,
        ),
        html.Tr([
            html.Td(html.Strong("Total  (After-Tax)"),
                    style={"borderTop": "2px solid #2a2a2a", "paddingTop": "12px",
                           "color": "#ffffff", "fontSize": "0.85rem"}),
            html.Td("", style={"borderTop": "2px solid #2a2a2a"}),
            html.Td(html.Strong(f"${at_total:,.0f}",
                                style={"color": g_color, "fontSize": "1.05rem"}),
                    style={"textAlign": "right", "borderTop": "2px solid #2a2a2a",
                           "paddingTop": "12px"}),
            html.Td("", style={"borderTop": "2px solid #2a2a2a"}),
        ]),
    ]

    acct_block = html.Div([
        html.Div([
            html.I(className="bi-table me-2",
                   style={"color": "#4a90e2", "fontSize": "0.85rem"}),
            html.Span("Account Breakdown at Retirement",
                      style={"fontWeight": 700, "fontSize": "0.80rem",
                             "color": "#cccccc"}),
            html.Span("  —  projected at the required return rate",
                      style={"color": "#777777", "fontSize": "0.70rem"}),
        ], style={"display": "flex", "alignItems": "center",
                  "marginBottom": "4px"}),
        html.Div(
            "Shows how much each account is worth at retirement — "
            "both before and after taxes — and how much you're contributing monthly.",
            style={"fontSize": "0.70rem", "color": "#999999",
                   "marginBottom": "12px", "lineHeight": "1.45"},
        ),
        dbc.Table(
            [
                html.Thead(html.Tr([
                    _th("Account"),
                    _th("Gross Future Value"),
                    _th("After-Tax Value"),
                    _th("Monthly Contrib"),
                ])),
                html.Tbody(rows),
            ],
            bordered=False, hover=True, size="sm",
            style={"backgroundColor": "transparent", "color": "#ffffff",
                   "marginBottom": "10px"},
        ),
        # Footnotes
        html.Div([
            html.Span("🟢 Roth (tax-free): ", style={"color": "#888888", "fontSize": "0.68rem"}),
            html.Span("no tax at withdrawal.  ",
                      style={"color": "#2ecc71", "fontSize": "0.68rem"}),
            html.Span("Taxable: ", style={"color": "#888888", "fontSize": "0.68rem"}),
            html.Span(f"{cg_rate*100:.0f}% capital gains on gains.  ",
                      style={"color": "#888", "fontSize": "0.68rem"}),
            html.Span("Trad 401k: ", style={"color": "#888888", "fontSize": "0.68rem"}),
            html.Span(f"{oi_rate*100:.0f}% income tax at withdrawal.",
                      style={"color": "#888", "fontSize": "0.68rem"}),
        ]),
    ], style={**_CARD_BOX, "marginBottom": "20px"})

    # ── Key assumptions chip row ──────────────────────────────────────────────
    assumptions_block = html.Div([
        html.Div([
            html.I(className="bi-sliders me-2",
                   style={"color": "#4a90e2", "fontSize": "0.85rem"}),
            html.Span("Key Assumptions Used",
                      style={"fontWeight": 700, "fontSize": "0.80rem",
                             "color": "#cccccc"}),
        ], style={"display": "flex", "alignItems": "center",
                  "marginBottom": "12px"}),
        dbc.Row([
            dbc.Col([
                _assumption_chip("Age", f"{v['current_age']} → {v['retirement_age']}  ({horizon} yrs)"),
                _assumption_chip("Retirement span",
                                 f"{years_in_retirement} yrs  (to age {v['life_expectancy']})"),
                _assumption_chip("Inflation", f"{inflation_rate*100:.1f}%/yr"),
            ], md=4),
            dbc.Col([
                _assumption_chip("Post-retirement return", f"{post_ret_rate*100:.1f}%/yr"),
                _assumption_chip("Contribution growth", f"{contrib_growth*100:.1f}%/yr"),
                _assumption_chip("Employer match",
                                 f"{match_rate*100:.0f}% up to {match_cap*100:.0f}% of salary"),
            ], md=4),
            dbc.Col([
                _assumption_chip("Income tax (Trad 401k)", f"{oi_rate*100:.0f}%"),
                _assumption_chip("Capital gains tax", f"{cg_rate*100:.0f}%"),
                _assumption_chip("Cost basis ratio", f"{cb_ratio*100:.0f}% of taxable FV"),
            ], md=4),
        ], className="g-0"),
    ], style={
        "backgroundColor": "#0d0d0d", "border": "1px solid #1e1e1e",
        "borderRadius": "6px", "padding": "14px 18px", "marginBottom": "4px",
    })

    return html.Div([
        html.Div("Planning Summary", className="section-title",
                 style={"marginBottom": "16px"}),
        goal_banner,
        kpi_row,
        progress_block,
        acct_block,
        assumptions_block,
        _raw_summary_details(summary_text),
        html.Div(className="divider"),
    ])


# ---------------------------------------------------------------------------
# UI builder: Monte Carlo section
# ---------------------------------------------------------------------------

def _mc_bullet(icon_cls: str, icon_color: str, text) -> html.Div:
    """One bullet row in the MC explanation box."""
    return html.Div([
        html.I(className=f"{icon_cls} me-2",
               style={"color": icon_color, "fontSize": "0.80rem", "flexShrink": 0}),
        html.Span(text, style={"color": "#bbbbbb", "fontSize": "0.75rem",
                               "lineHeight": "1.5"}),
    ], style={"display": "flex", "alignItems": "flex-start",
              "marginBottom": "6px"})


def _build_mc_ui(
    scenarios: dict,
    horizon: int,
    total_port: float,
    planning: dict | None,
) -> html.Div:
    if not scenarios:
        return dbc.Alert("No Monte Carlo results returned.", color="warning")

    chart_target = planning["required_nest_egg"] if planning else None

    # ── Fan chart ─────────────────────────────────────────────────────────────
    fig = go.Figure()
    for name, sc in scenarios.items():
        colour = _SCENARIO_COLOURS.get(name, "#aaa")
        projs  = sc.get("projections", [])
        ages   = [p["age"] for p in projs]
        p10    = [p["p10"] for p in projs]
        p50    = [p["p50"] for p in projs]
        p90    = [p["p90"] for p in projs]

        fig.add_trace(go.Scatter(
            x=ages + ages[::-1], y=p90 + p10[::-1],
            fill="toself", fillcolor=colour, opacity=0.10,
            line=dict(width=0), showlegend=False, name=f"{name} band",
        ))
        fig.add_trace(go.Scatter(
            x=ages, y=p50, mode="lines",
            name=sc.get("label", name),
            line=dict(color=colour, width=2.5),
        ))

    if chart_target:
        fig.add_hline(
            y=chart_target, line_dash="dash", line_color="#f0c040",
            annotation_text=f"Required Nest Egg: ${chart_target:,.0f}",
            annotation_position="bottom right",
            annotation_font=dict(color="#f0c040"),
        )

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#111111", plot_bgcolor="#111111",
        font=dict(color="#ffffff"),
        legend=dict(orientation="h", y=-0.15, font=dict(color="#ffffff")),
        margin=dict(l=60, r=20, t=30, b=60),
        xaxis=dict(title="Age", gridcolor="#2a2a2a", color="#ffffff"),
        yaxis=dict(title="Portfolio Value (Real $)", gridcolor="#2a2a2a",
                   tickformat="$,.0f", color="#ffffff"),
        height=420,
    )
    chart = dcc.Graph(figure=fig, config={"displayModeBar": False})

    # ── What-is-MC explanation box ────────────────────────────────────────────
    explanation = html.Div([
        html.Div([
            html.I(className="bi-info-circle-fill me-2",
                   style={"color": "#4a90e2", "fontSize": "0.90rem"}),
            html.Span("What is Monte Carlo Simulation?",
                      style={"fontWeight": 700, "fontSize": "0.84rem",
                             "color": "#ffffff"}),
        ], style={"display": "flex", "alignItems": "center",
                  "marginBottom": "10px"}),
        html.Div(
            "Instead of assuming a single fixed return every year, this simulation "
            "runs your portfolio through thousands of random but historically realistic "
            "market paths — some great years, some crashes — to show you a range of "
            "possible futures rather than one optimistic number.",
            style={"fontSize": "0.76rem", "color": "#bbbbbb",
                   "lineHeight": "1.6", "marginBottom": "14px"},
        ),
        html.Div("How to read the fan chart:",
                 style={"fontSize": "0.74rem", "color": "#888888",
                        "fontWeight": 600, "marginBottom": "8px",
                        "textTransform": "uppercase", "letterSpacing": "0.06em"}),
        _mc_bullet("bi-arrow-up-circle-fill", "#2ecc71",
                   "Upper band (P90) — Only 10% of simulated paths perform this well. "
                   "Think of this as the optimistic ceiling."),
        _mc_bullet("bi-dash-circle-fill", "#4a90e2",
                   "Median line (P50) — Half of all paths land above this line. "
                   "Your most realistic central expectation."),
        _mc_bullet("bi-arrow-down-circle-fill", "#e74c3c",
                   "Lower band (P10) — Only 10% of paths perform worse than this. "
                   "Your floor even in unfavorable markets."),
        html.Div("Three scenarios modelled:",
                 style={"fontSize": "0.74rem", "color": "#888888",
                        "fontWeight": 600, "marginBottom": "8px", "marginTop": "12px",
                        "textTransform": "uppercase", "letterSpacing": "0.06em"}),
        _mc_bullet("bi-graph-down", _SCENARIO_COLOURS["conservative"],
                   [html.Strong("Conservative: ", style={"color": _SCENARIO_COLOURS["conservative"]}),
                    "Lower expected returns with higher volatility — "
                    "models a prolonged bear-market environment."]),
        _mc_bullet("bi-graph-up-arrow", _SCENARIO_COLOURS["expected"],
                   [html.Strong("Expected: ", style={"color": _SCENARIO_COLOURS["expected"]}),
                    "Returns based on long-term historical averages — "
                    "the most likely baseline scenario."]),
        _mc_bullet("bi-stars", _SCENARIO_COLOURS["optimistic"],
                   [html.Strong("Optimistic: ", style={"color": _SCENARIO_COLOURS["optimistic"]}),
                    "Higher returns with lower volatility — "
                    "models a sustained bull-market environment."]),
    ], style={
        "backgroundColor": "#0d0d0d", "border": "1px solid #1e1e1e",
        "borderLeft": "4px solid #4a90e2",
        "borderRadius": "6px", "padding": "16px 20px",
        "marginBottom": "22px",
    })

    # ── Per-scenario narrative cards ──────────────────────────────────────────
    sc_cards = []
    for name, sc in scenarios.items():
        colour    = _SCENARIO_COLOURS.get(name, "#aaa")
        label     = sc.get("label", name)
        readiness = sc.get("readiness_score")
        projs     = sc.get("projections", [])

        # Extract final P10 / P50 / P90
        final_p50 = sc.get("final_p50") or (projs[-1]["p50"] if projs else 0)
        final_p10 = sc.get("final_p10") or (projs[-1]["p10"] if projs else 0)
        final_p90 = sc.get("final_p90") or (projs[-1]["p90"] if projs else 0)

        # Readiness badge
        if readiness is not None:
            pct = readiness * 100
            if pct >= 75:
                r_color, r_bg = "#2ecc71", "rgba(46,204,113,0.10)"
            elif pct >= 50:
                r_color, r_bg = "#f39c12", "rgba(243,156,18,0.10)"
            else:
                r_color, r_bg = "#e74c3c", "rgba(231,76,60,0.10)"
            readiness_el = html.Div([
                html.Div([
                    html.Span(f"{pct:.0f}%",
                              style={"fontSize": "1.5rem", "fontWeight": 800,
                                     "color": r_color, "lineHeight": "1.1"}),
                    html.Span(" success rate",
                              style={"color": "#aaaaaa", "fontSize": "0.74rem",
                                     "marginLeft": "6px"}),
                ], style={"marginBottom": "3px"}),
                html.Div(
                    f"In {pct:.0f}% of simulated market paths, your portfolio "
                    f"reaches the ${chart_target:,.0f} nest egg goal "
                    "by retirement." if chart_target else
                    f"{pct:.0f}% of paths end with a positive balance.",
                    style={"fontSize": "0.72rem", "color": "#999999",
                           "lineHeight": "1.45"},
                ),
            ], style={
                "backgroundColor": r_bg,
                "borderRadius": "4px", "padding": "10px 12px",
                "marginBottom": "12px",
            })
        else:
            readiness_el = html.Div(
                "Enter Monthly Spending to see goal success probability.",
                style={"color": "#666", "fontSize": "0.72rem",
                       "fontStyle": "italic", "marginBottom": "12px"},
            )

        def _outcome_row(label_str, value, note, val_color):
            return html.Div([
                html.Div([
                    html.Span(label_str,
                              style={"color": "#888888", "fontSize": "0.68rem",
                                     "textTransform": "uppercase",
                                     "letterSpacing": "0.06em"}),
                    html.Span(f"  ${value:,.0f}",
                              style={"color": val_color, "fontWeight": 700,
                                     "fontSize": "0.90rem"}),
                ], style={"display": "flex", "alignItems": "baseline",
                          "gap": "4px", "marginBottom": "1px"}),
                html.Div(note, style={"color": "#777777", "fontSize": "0.68rem",
                                      "paddingLeft": "2px", "marginBottom": "8px"}),
            ])

        sc_cards.append(dbc.Col(html.Div([
            # Scenario label
            html.Div([
                html.Span("●  ", style={"color": colour}),
                html.Span(label.upper(),
                          style={"fontSize": "0.72rem", "color": colour,
                                 "fontWeight": 700, "letterSpacing": "0.10em"}),
            ], style={"marginBottom": "14px"}),

            # Readiness badge
            readiness_el,

            # P50 / P10 / P90 outcome rows
            _outcome_row("Median outcome (P50)", final_p50,
                         "In a typical simulation — half of all paths end above this.",
                         "#cccccc"),
            _outcome_row("Worst 10%  (P10)", final_p10,
                         "Only 1 in 10 simulations ends lower than this. Your downside floor.",
                         "#e74c3c"),
            _outcome_row("Best 10%  (P90)", final_p90,
                         "Only 1 in 10 simulations ends higher than this. Your upside ceiling.",
                         "#2ecc71"),

        ], style={
            "backgroundColor": "#111111",
            "border": f"1px solid #2a2a2a",
            "borderTop": f"3px solid {colour}",
            "borderRadius": "6px",
            "padding": "16px 18px",
            "height": "100%",
        }), md=4))

    # ── Methodology footnote ──────────────────────────────────────────────────
    footnote = html.Div([
        html.I(className="bi-exclamation-triangle me-1",
               style={"color": "#555", "fontSize": "0.68rem"}),
        html.Span(
            f"Projections over {horizon} years using log-normal annual returns.  "
            "Real dollars (inflation-adjusted).  Bands show 10th–90th percentile range.  "
            "Accounts: taxable (capital gains tax), Traditional 401k (ordinary income tax), "
            "Roth 401k + Roth IRA (tax-free withdrawals).  "
            "Past performance does not guarantee future results.",
            style={"color": "#555555", "fontSize": "0.68rem"},
        ),
    ], style={"display": "flex", "alignItems": "flex-start", "gap": "4px",
              "marginTop": "16px"})

    return html.Div([
        html.Div(
            f"Monte Carlo Simulation  —  Starting Portfolio: ${total_port:,.0f}",
            className="section-title",
            style={"marginBottom": "16px"},
        ),
        explanation,
        html.Div(className="chart-container", children=[chart]),
        html.Div(className="divider"),
        dbc.Row(sc_cards, className="g-3"),
        footnote,
        html.Div(className="divider"),
    ])


# ---------------------------------------------------------------------------
# Summary text: Korean/English bilingual
# ---------------------------------------------------------------------------

def _format_summary(
    v: dict,
    planning: dict | None,
    total_port: float,
    inflation_rate: float,
    post_ret_rate: float,
    contrib_growth_rate: float,
    match_rate: float,
    match_cap: float,
    oi_rate: float,
    cg_rate: float,
    cb_ratio: float,
    monthly_taxable: float,
    sim_mode: str,
) -> str:
    """Generate a Korean/English bilingual planning summary text block."""
    horizon = v["retirement_age"] - v["current_age"]
    lines = [
        "=" * 62,
        "        은퇴 플래닝 요약  /  Retirement Planning Summary",
        "=" * 62,
        "",
        "[입력 파라미터 / Input Parameters]",
        f"  현재 나이 / Current Age           : {v['current_age']}세 (age)",
        f"  은퇴 나이 / Retirement Age         : {v['retirement_age']}세 (age)",
        f"  기대 수명 / Life Expectancy        : {v['life_expectancy']}세 (age)",
        f"  투자 기간 / Investment Horizon     : {horizon}년 (years)",
        "",
        f"  현재 과세 계좌 / Taxable Balance   : ${v['current_value']:>12,.0f}",
        f"  현재 전통 401k / Trad 401k         : ${v['trad_401k_balance']:>12,.0f}",
        f"  현재 로스 401k / Roth 401k         : ${v['roth_401k_balance']:>12,.0f}",
        f"  현재 로스 IRA  / Roth IRA          : ${v['roth_ira_balance']:>12,.0f}",
        f"  총 포트폴리오 / Total Portfolio    : ${total_port:>12,.0f}",
        "",
        f"  월 지출 / Monthly Spending         : ${v['monthly_spending']:>10,.0f}  (today's $)",
        f"  연봉 / Annual Salary               : ${v['annual_salary']:>10,.0f}",
        f"  월 과세 납입 / Monthly Taxable     : ${monthly_taxable:>10,.0f}/mo",
        f"  월 전통 401k / Monthly Trad 401k   : ${v['monthly_trad_401k']:>10,.0f}/mo",
        f"  월 로스 401k / Monthly Roth 401k   : ${v['monthly_roth_401k']:>10,.0f}/mo",
        f"  월 로스 IRA  / Monthly Roth IRA    : ${v['monthly_roth_ira']:>10,.0f}/mo",
        f"  고용주 매칭 / Employer Match        : {match_rate*100:.0f}% up to {match_cap*100:.0f}% of salary",
        "",
        "[경제 가정 / Economic Assumptions]",
        f"  인플레이션 / Inflation Rate        : {inflation_rate*100:.1f}%  (~2.5% US 10yr avg)",
        f"  은퇴 후 수익률 / Post-Ret Return   : {post_ret_rate*100:.1f}%",
        f"  납입 증가율 / Contribution Growth  : {contrib_growth_rate*100:.1f}%",
        f"  시뮬레이션 모드 / Simulation Mode  : {'Fast (cached)' if sim_mode == 'fast' else 'True Random'}",
        "",
        "[세금 / Tax Rates]",
        f"  보통소득세 / Ordinary Income       : {oi_rate*100:.1f}%",
        f"  자본이득세 / Capital Gains         : {cg_rate*100:.1f}%",
        f"  비용 기준 / Cost Basis Ratio       : {cb_ratio*100:.1f}%",
    ]

    if planning:
        req_rate_pct = planning["required_return_rate"] * 100
        nest_egg     = planning["required_nest_egg"]
        monthly_ret  = planning["monthly_spending_at_retirement"]
        fv_tax       = planning["fv_taxable"]
        fv_trad      = planning["fv_trad_401k"]
        fv_roth      = planning["fv_roth_401k"]
        fv_roth_ira  = planning.get("fv_roth_ira", 0.0)
        at_total     = planning["after_tax_total"]
        eff_trad     = planning["eff_monthly_trad"]
        eff_roth     = planning["eff_monthly_roth"]
        eff_match    = planning["eff_monthly_match"]
        eff_roth_ira = planning.get("eff_monthly_roth_ira", 0.0)
        total_401k   = eff_trad + eff_roth + eff_match

        at_taxable  = fv_tax - fv_tax * (1 - cb_ratio) * cg_rate
        at_trad     = fv_trad * (1 - oi_rate)
        shortfall   = at_total - nest_egg
        goal_str    = (
            f"달성 가능 / Met  (Surplus: ${shortfall:+,.0f})"
            if shortfall >= 0
            else f"부족 / Shortfall: ${shortfall:,.0f}"
        )
        verdict = (
            "Achievable (<= 6%)" if req_rate_pct <= 6
            else "Stretch Goal (6-10%)" if req_rate_pct <= 10
            else "Aggressive / High Risk (>10%)"
        )

        lines += [
            "",
            "[계획 엔진 결과 / Planning Engine Results]",
            f"  은퇴 시 월 지출 (명목) / Monthly Spend at Retirement : ${monthly_ret:>12,.0f}",
            f"  필요 은퇴 자금 / Required Nest Egg                   : ${nest_egg:>12,.0f}",
            f"  필요 연수익률 / Required Annual Return Rate          : {req_rate_pct:.2f}%  ({verdict})",
            "  " + "-" * 58,
            f"  과세 계좌 FV / Taxable FV (gross)                    : ${fv_tax:>12,.0f}",
            f"  과세 계좌 FV / Taxable FV (after-tax)                : ${at_taxable:>12,.0f}",
            f"  전통 401k FV / Trad 401k FV (gross)                  : ${fv_trad:>12,.0f}",
            f"  전통 401k FV / Trad 401k FV (after-tax)              : ${at_trad:>12,.0f}",
            f"  로스 401k FV / Roth 401k FV (tax-free)               : ${fv_roth:>12,.0f}",
            f"  로스 IRA FV  / Roth IRA FV  (tax-free)               : ${fv_roth_ira:>12,.0f}",
            "  " + "-" * 58,
            f"  세후 총액 / After-Tax Total                          : ${at_total:>12,.0f}",
            f"  목표 달성 / Goal Status                              : {goal_str}",
            "",
            "[효과적인 월 납입 / Effective Monthly Contributions]",
            "  (IRS 한도 적용 후 / After IRS limits)",
            f"  전통 401k / Trad 401k                                : ${eff_trad:>8,.0f}/mo",
            f"  로스 401k / Roth 401k                                : ${eff_roth:>8,.0f}/mo",
            f"  고용주 매칭 / Employer Match                         : ${eff_match:>8,.0f}/mo",
            f"  총 401k / Total 401k                                 : ${total_401k:>8,.0f}/mo",
            f"  로스 IRA / Roth IRA                                  : ${eff_roth_ira:>8,.0f}/mo",
            f"  과세 계좌 / Taxable Account                          : ${monthly_taxable:>8,.0f}/mo",
        ]
    else:
        lines += [
            "",
            "[계획 엔진 / Planning Engine]",
            "  월 지출 미입력 / Monthly Spending not set — planning skipped.",
            "  플래닝 활성화: 'Monthly Spending Today' 입력 필요.",
            "  (Enter monthly spending above to enable planning mode.)",
        ]

    lines += ["", "=" * 62]
    return "\n".join(lines)
