"""
frontend.pages.calendar
========================
Page – Economic Calendar.

Sections
--------
1. Countdown to next FOMC meeting and next CPI release.
2. Upcoming events list (next 30 / 60 / 90 days, filterable by type).
3. Seed button to populate DB with hardcoded schedule.
"""

from __future__ import annotations

from datetime import date, timedelta

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, callback, dcc, html

from frontend.api_client import get_calendar, seed_calendar

dash.register_page(__name__, path="/calendar", name="Econ Calendar", title="Economic Calendar")

_TYPE_COLOURS = {
    "fomc":      "#f0c040",
    "inflation": "#e67e22",
    "labor":     "#2ecc71",
    "pmi":       "#3498db",
    "other":     "#888888",
}
_TYPE_ICONS = {
    "fomc":      "bi-bank",
    "inflation": "bi-graph-up",
    "labor":     "bi-people",
    "pmi":       "bi-bar-chart",
    "other":     "bi-calendar-event",
}

_WINDOW_OPTIONS = [
    {"label": "30 days", "value": 30},
    {"label": "60 days", "value": 60},
    {"label": "90 days", "value": 90},
]
_TYPE_OPTIONS = [
    {"label": "All",       "value": "all"},
    {"label": "FOMC",      "value": "fomc"},
    {"label": "Inflation", "value": "inflation"},
    {"label": "Labor",     "value": "labor"},
]

_IMPORTANCE_OPTIONS = [
    {"label": "All",    "value": "all"},
    {"label": "High",   "value": "High"},
    {"label": "Medium", "value": "Medium"},
    {"label": "Low",    "value": "Low"},
]

# Styling by importance level
_IMPORTANCE_STYLE = {
    "High":   {"fontWeight": "700", "fontSize": "0.92rem", "borderLeft": "3px solid #e94560"},
    "Medium": {"fontWeight": "500", "fontSize": "0.88rem", "borderLeft": "3px solid #f0c040"},
    "Low":    {"fontWeight": "400", "fontSize": "0.82rem", "borderLeft": "3px solid #444", "opacity": "0.7"},
}
_IMPORTANCE_BADGE = {
    "High":   {"color": "#e94560", "fontSize": "0.68rem", "marginLeft": "8px",
               "textTransform": "uppercase", "fontWeight": "700"},
    "Medium": {"color": "#f0c040", "fontSize": "0.68rem", "marginLeft": "8px",
               "textTransform": "uppercase"},
    "Low":    {"color": "#555", "fontSize": "0.68rem", "marginLeft": "8px",
               "textTransform": "uppercase"},
}


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

layout = html.Div([
    html.Div([
        html.Span("Economic ", className="page-title"),
        html.Span("Calendar", className="page-title title-accent"),
    ], style={"marginBottom": "20px"}),

    dcc.Store(id="cal-data-store", data={}),

    # Controls
    dbc.Row([
        dbc.Col([
            html.Div("Window", className="threshold-label"),
            dbc.RadioItems(
                id="cal-window",
                options=_WINDOW_OPTIONS,
                value=30,
                inline=True,
                style={"color": "#ffffff"},
            ),
        ], md=3),
        dbc.Col([
            html.Div("Type", className="threshold-label"),
            dbc.RadioItems(
                id="cal-type-filter",
                options=_TYPE_OPTIONS,
                value="all",
                inline=True,
                style={"color": "#ffffff"},
            ),
        ], md=3),
        dbc.Col([
            html.Div("Importance", className="threshold-label"),
            dbc.RadioItems(
                id="cal-importance-filter",
                options=_IMPORTANCE_OPTIONS,
                value="all",
                inline=True,
                style={"color": "#ffffff"},
            ),
        ], md=3),
        dbc.Col([
            dbc.Button(
                [html.I(className="bi-calendar-plus me-2"), "Seed Calendar"],
                id="cal-seed-btn", color="secondary", size="sm", outline=True,
                style={"float": "right"},
                title="Populate DB with FOMC/CPI/NFP schedule",
            ),
        ], md=3),
    ], className="mb-3"),

    dcc.Loading(html.Div(id="cal-seed-status",
                         style={"fontSize": "0.82rem", "color": "#2ecc71", "marginBottom": "8px"})),

    # Countdown row
    html.Div("Countdowns", className="section-title"),
    dbc.Row(id="cal-countdown-row", className="g-3 mb-4"),

    # Events list
    html.Div("Upcoming Events", className="section-title"),
    dcc.Loading(html.Div(id="cal-events-list"), type="circle", color="#f0c040"),
])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ev_importance_norm(ev: dict) -> str:
    """Normalise the raw importance string to 'High', 'Medium', or 'Low'."""
    raw = str(ev.get("importance", "")).strip().capitalize()
    if raw in ("High", "Medium", "Low"):
        return raw
    return ""


def _days_until(events: list[dict], event_type: str) -> int | None:
    today = date.today()
    for ev in events:
        if ev.get("event_type") == event_type:
            ev_date = ev.get("event_date")
            if isinstance(ev_date, str):
                ev_date = date.fromisoformat(ev_date)
            if ev_date and ev_date >= today:
                return (ev_date - today).days
    return None


def _countdown_card(label: str, days: int | None, colour: str, icon: str) -> dbc.Col:
    days_str = f"{days}d" if days is not None else "—"
    sub = "days away" if days is not None else "No data — seed calendar"
    return dbc.Col(
        html.Div(className="kpi-card", children=[
            html.Div([html.I(className=f"{icon} me-2", style={"color": colour}), label],
                     className="kpi-label"),
            html.Div(days_str, className="kpi-value",
                     style={"fontSize": "2rem", "color": colour}),
            html.Div(sub, style={"fontSize": "0.68rem", "color": "#888"}),
        ]),
        xs=6, sm=4, md=3,
    )


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

@callback(
    Output("cal-countdown-row", "children"),
    Output("cal-events-list",   "children"),
    Input("cal-window",              "value"),
    Input("cal-type-filter",         "value"),
    Input("cal-importance-filter",   "value"),
    Input("cal-data-store",          "data"),
)
def update_calendar(window, type_filter, importance_filter, _store):
    events = get_calendar(days=window) or []

    # Countdowns
    fomc_days = _days_until(events, "fomc")
    cpi_days  = _days_until(events, "inflation")
    nfp_days  = _days_until(events, "labor")

    countdown_row = [
        _countdown_card("Next FOMC",   fomc_days, "#f0c040", "bi-bank"),
        _countdown_card("Next CPI",    cpi_days,  "#e67e22", "bi-graph-up"),
        _countdown_card("Next NFP",    nfp_days,  "#2ecc71", "bi-people"),
    ]

    # Filter events
    if type_filter != "all":
        events = [e for e in events if e.get("event_type") == type_filter]
    if importance_filter != "all":
        events = [e for e in events if ev_importance_norm(e) == importance_filter]

    if not events:
        events_list = html.Div(
            "No events found. Click 'Seed Calendar' to load the default schedule.",
            style={"color": "#888", "fontSize": "0.85rem", "padding": "16px"},
        )
    else:
        # Group by date
        from collections import defaultdict
        by_date: dict[str, list] = defaultdict(list)
        for ev in events:
            d = str(ev.get("event_date", ""))
            by_date[d].append(ev)

        rows = []
        today = date.today()
        for d_str in sorted(by_date.keys()):
            try:
                d = date.fromisoformat(d_str)
            except Exception:
                d = None
            days_away = (d - today).days if d else None
            is_today  = days_away == 0
            is_soon   = days_away is not None and days_away <= 7

            date_badge_style = {
                "fontSize": "0.72rem", "fontWeight": "700",
                "padding": "2px 8px", "borderRadius": "3px", "marginRight": "10px",
                "color": "#111" if is_today else "#fff",
                "backgroundColor": "#f0c040" if is_today else ("#e94560" if is_soon else "#2a2a2a"),
            }
            day_label = "Today" if is_today else (f"in {days_away}d" if days_away is not None else "")
            date_str  = d.strftime("%b %d, %Y") if d else d_str

            date_row = html.Div([
                html.Span(date_str, style=date_badge_style),
                html.Span(day_label, style={"fontSize": "0.70rem", "color": "#888"}),
            ], style={"padding": "8px 0 4px", "borderTop": "1px solid #1e1e1e",
                      "marginTop": "8px"})
            rows.append(date_row)

            for ev in by_date[d_str]:
                et = ev.get("event_type", "other")
                ec = _TYPE_COLOURS.get(et, "#888")
                ei = _TYPE_ICONS.get(et, "bi-calendar-event")
                imp = ev_importance_norm(ev)
                actual   = ev.get("actual")
                forecast = ev.get("forecast")
                previous = ev.get("previous")

                meta_parts = []
                if actual:
                    meta_parts.append(html.Span(f"Actual: {actual}",
                                                style={"color": "#2ecc71", "marginRight": "10px",
                                                       "fontSize": "0.75rem"}))
                if forecast:
                    meta_parts.append(html.Span(f"Fcst: {forecast}",
                                                style={"color": "#f0c040", "marginRight": "10px",
                                                       "fontSize": "0.75rem"}))
                if previous:
                    meta_parts.append(html.Span(f"Prev: {previous}",
                                                style={"color": "#888", "fontSize": "0.75rem"}))

                row_style = {
                    "padding": "6px 12px", "marginLeft": "8px",
                    **_IMPORTANCE_STYLE.get(imp, {}),
                }
                rows.append(html.Div([
                    html.Div([
                        html.I(className=f"{ei} me-2", style={"color": ec}),
                        html.Span(ev.get("event_name", ""), style={"color": "#fff",
                                  "fontWeight": row_style.get("fontWeight", "600"),
                                  "fontSize": row_style.get("fontSize", "0.88rem")}),
                        html.Span(imp, style=_IMPORTANCE_BADGE.get(imp, {})) if imp else None,
                    ]),
                    html.Div(meta_parts) if meta_parts else None,
                ], style={"padding": "6px 12px", "marginLeft": "8px",
                          "borderLeft": row_style.get("borderLeft", "none"),
                          "opacity": row_style.get("opacity", "1"),
                          "marginBottom": "2px"}))

        events_list = html.Div(rows)

    return countdown_row, events_list


@callback(
    Output("cal-seed-status", "children"),
    Output("cal-data-store",  "data"),
    Input("cal-seed-btn",     "n_clicks"),
    prevent_initial_call=True,
)
def seed_calendar_cb(_):
    import time
    res = seed_calendar() or {}
    count = res.get("events_seeded", 0)
    return f"Seeded {count} calendar events.", {"ts": time.time()}
