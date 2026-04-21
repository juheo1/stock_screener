"""
frontend.app
============
Dash multi-page application entry point.

The app renders a persistent sidebar navigation and a dynamic page-content
area.  Each page is a separate module in ``frontend/pages/``.

Run directly::

    python frontend/app.py

Or via the convenience script::

    python scripts/run_server.py --frontend-only
"""

from __future__ import annotations

import sys
import os

# Make sure the project root is on the Python path when running directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import dash
import dash_bootstrap_components as dbc
from dash import Dash, Input, Output, State, callback, ctx, dcc, html

from frontend.config import API_BASE_URL, DASH_DEBUG, DASH_HOST, DASH_PORT

# ---------------------------------------------------------------------------
# App initialisation
# ---------------------------------------------------------------------------

app = Dash(
    __name__,
    use_pages=True,
    pages_folder="pages",
    assets_folder="assets",
    external_stylesheets=[dbc.themes.DARKLY, dbc.icons.BOOTSTRAP],
    suppress_callback_exceptions=True,
    title="Stock Intelligence Suite",
    update_title=None,
)

server = app.server  # Expose Flask server for WSGI deployment if needed

# ---------------------------------------------------------------------------
# Navigation items
# ---------------------------------------------------------------------------

NAV_ITEMS = [
    {"label": "Intelligence Hub",    "href": "/",            "icon": "bi-speedometer2"},
    {"label": "Stock Screener",      "href": "/screener",    "icon": "bi-funnel"},
    {"label": "Screener ROK",        "href": "/screener-rok","icon": "bi-globe-asia-australia"},
    {"label": "ETF Screener",        "href": "/etf",         "icon": "bi-collection"},
    {"label": "Technical Chart",     "href": "/technical",  "icon": "bi-bar-chart-line-fill"},
    {"label": "Strategy Scanner",    "href": "/scanner",    "icon": "bi-radar"},
    {"label": "Trade Tracker",       "href": "/trades",     "icon": "bi-journal-check"},
    {"label": "Zombie Kill List",    "href": "/zombies",    "icon": "bi-radioactive"},
    {"label": "Batch Compare",       "href": "/compare",    "icon": "bi-bar-chart-steps"},
    {"label": "Retirement",          "href": "/retirement", "icon": "bi-graph-up-arrow"},
    {"label": "Metals Intel",        "href": "/metals",     "icon": "bi-gem"},
    {"label": "Macro Monitor",       "href": "/macro",      "icon": "bi-activity"},
    {"label": "Fed Liquidity",       "href": "/liquidity",  "icon": "bi-bank"},
    {"label": "News & Sentiment",    "href": "/sentiment",  "icon": "bi-newspaper"},
    {"label": "Econ Calendar",       "href": "/calendar",   "icon": "bi-calendar-event"},
]


def _nav_link(label: str, href: str, icon: str) -> html.A:
    return html.A(
        [
            html.I(className=f"{icon} nav-icon"),
            label,
        ],
        href=href,
        className="nav-link-item",
        id=f"nav-{href.strip('/') or 'hub'}",
    )


sidebar = html.Div(
    id="sidebar",
    children=[
        html.Div(
            className="sidebar-header",
            children=[
                html.H4("STOCK INTEL"),
                html.Small("Intelligence Suite v1.0"),
            ],
        ),
        html.Div(
            style={"paddingTop": "8px"},
            children=[_nav_link(**item) for item in NAV_ITEMS],
        ),
        # Spacer
        html.Div(style={"flex": "1"}),
        html.Div(
            style={"padding": "12px 16px", "borderTop": "1px solid #2a2a2a"},
            children=[
                html.Small(
                    f"API: {API_BASE_URL}",
                    style={"color": "#ffffff", "fontSize": "0.70rem"},
                ),
            ],
        ),
    ],
    style={"display": "flex", "flexDirection": "column"},
)

# ---------------------------------------------------------------------------
# Root layout
# ---------------------------------------------------------------------------

app.layout = html.Div(
    style={"display": "flex", "minHeight": "100vh"},
    children=[
        dcc.Location(id="url", refresh=False),
        # Persistent stores for the Retirement Planner.
        # storage_type="local" keeps the values across browser sessions.
        dcc.Store(id="ret-form-store",     storage_type="local"),
        dcc.Store(id="ret-profiles-store", storage_type="local"),
        # Sidebar open/closed state (for mobile toggle)
        dcc.Store(id="sidebar-open", data=False),
        # Hamburger button — visible only on mobile (CSS controls display)
        html.Button(
            html.I(className="bi-list", style={"fontSize": "1.3rem"}),
            id="sidebar-toggle",
            className="sidebar-hamburger",
            n_clicks=0,
        ),
        # Dark overlay behind the sidebar on mobile
        html.Div(id="sidebar-overlay", className="sidebar-overlay", n_clicks=0),
        # Sidebar wrapper — width managed by CSS (.sidebar-wrapper)
        html.Div(
            id="sidebar-wrapper",
            className="sidebar-wrapper",
            children=[sidebar],
        ),
        # Page content
        html.Div(
            id="page-content",
            children=[dash.page_container],
            style={"flex": "1", "overflow": "auto"},
        ),
    ],
)

# ---------------------------------------------------------------------------
# Callback: highlight active nav item
# ---------------------------------------------------------------------------

@callback(
    [Output(f"nav-{item['href'].strip('/') or 'hub'}", "className") for item in NAV_ITEMS],
    Input("url", "pathname"),
)
def highlight_active_nav(pathname: str):
    classes = []
    for item in NAV_ITEMS:
        href = item["href"]
        is_active = (
            (href == "/" and pathname == "/")
            or (href != "/" and pathname.startswith(href))
        )
        classes.append("nav-link-item active" if is_active else "nav-link-item")
    return classes


# ---------------------------------------------------------------------------
# Callback: mobile sidebar toggle
# ---------------------------------------------------------------------------

@callback(
    Output("sidebar-open", "data"),
    Input("sidebar-toggle", "n_clicks"),
    Input("sidebar-overlay", "n_clicks"),
    State("sidebar-open", "data"),
    prevent_initial_call=True,
)
def toggle_sidebar(_toggle, _overlay, is_open):
    if ctx.triggered_id == "sidebar-toggle":
        return not is_open
    return False  # overlay click always closes


@callback(
    Output("sidebar-wrapper", "className"),
    Output("sidebar-overlay", "className"),
    Input("sidebar-open", "data"),
)
def update_sidebar_class(is_open):
    if is_open:
        return "sidebar-wrapper sidebar-visible", "sidebar-overlay sidebar-overlay-visible"
    return "sidebar-wrapper", "sidebar-overlay"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(
        host=DASH_HOST,
        port=DASH_PORT,
        debug=DASH_DEBUG,
    )
