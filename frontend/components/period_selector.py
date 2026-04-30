"""
frontend.components.period_selector
====================================
Reusable time-period selector for daily OHLCV charts.

Public API
----------
PERIOD_OPTIONS          List of (label, value) pairs for the selector buttons.
DAILY_PLUS_INTERVALS    Set of interval keys that support period selection.
period_selector_row     Build the button-row layout element for a page.
slice_df_by_period      Slice a DatetimeIndex DataFrame to the chosen period.
"""
from __future__ import annotations

import pandas as pd

# ---------------------------------------------------------------------------
# Period options
# ---------------------------------------------------------------------------

PERIOD_OPTIONS: list[tuple[str, str]] = [
    ("1M",  "1mo"),
    ("3M",  "3mo"),
    ("6M",  "6mo"),
    ("YTD", "ytd"),
    ("1Y",  "1y"),
    ("2Y",  "2y"),
    ("5Y",  "5y"),
    ("Max", "max"),
]

_DEFAULT_PERIOD = "1y"

# Interval keys from INTERVAL_CFG that should show the period selector
DAILY_PLUS_INTERVALS = {"1D", "1W", "1MON", "3MON", "6MON", "12MON"}


# ---------------------------------------------------------------------------
# DataFrame slicer
# ---------------------------------------------------------------------------

def slice_df_by_period(df: pd.DataFrame | None, period: str) -> pd.DataFrame | None:
    """Return a copy of *df* trimmed to the last *period* of history.

    Parameters
    ----------
    df:
        OHLCV DataFrame with a DatetimeIndex.
    period:
        One of the values in PERIOD_OPTIONS, e.g. ``"1y"``, ``"6mo"``, ``"max"``.

    Returns
    -------
    Sliced DataFrame, or the original when period is ``"max"`` or df is empty.
    """
    if df is None or df.empty or period == "max":
        return df

    now = df.index.max()

    _offsets = {
        "1mo": pd.DateOffset(months=1),
        "3mo": pd.DateOffset(months=3),
        "6mo": pd.DateOffset(months=6),
        "1y":  pd.DateOffset(years=1),
        "2y":  pd.DateOffset(years=2),
        "5y":  pd.DateOffset(years=5),
    }

    if period == "ytd":
        start = pd.Timestamp(now.year, 1, 1)
    else:
        offset = _offsets.get(period)
        if offset is None:
            return df
        start = now - offset

    # Normalise tz so comparison works regardless of index tz-awareness
    if df.index.tzinfo is not None:
        start = start.tz_localize(df.index.tzinfo) if start.tzinfo is None else start
    else:
        if hasattr(start, "tzinfo") and start.tzinfo is not None:
            start = start.tz_localize(None)

    sliced = df.loc[df.index >= start]
    return sliced if not sliced.empty else df


# ---------------------------------------------------------------------------
# Layout builder
# ---------------------------------------------------------------------------

def period_selector_row(id_prefix: str, default: str = _DEFAULT_PERIOD):
    """Return a Dash layout element containing the period-selector button row.

    The element has ``id=f"{id_prefix}-period-row"`` so callers can
    show/hide it based on the active interval.

    Each button has ``id={"type": f"{id_prefix}-period-btn", "index": value}``.

    Parameters
    ----------
    id_prefix:
        Namespace prefix, e.g. ``"tech"`` or ``"scanner"``.
    default:
        Initially highlighted period value (default: ``"1y"``).
    """
    import dash_bootstrap_components as dbc
    from dash import dcc, html

    buttons = []
    for label, value in PERIOD_OPTIONS:
        is_active = (value == default)
        buttons.append(
            dbc.Button(
                label,
                id={"type": f"{id_prefix}-period-btn", "index": value},
                size="sm",
                color="primary" if is_active else "secondary",
                outline=not is_active,
                n_clicks=0,
                style={
                    "fontSize": "0.72rem",
                    "padding": "2px 9px",
                    "minWidth": "34px",
                },
            )
        )

    return html.Div(
        id=f"{id_prefix}-period-row",
        children=[
            html.Span(
                "PERIOD",
                style={
                    "color": "#444444",
                    "fontSize": "0.66rem",
                    "fontWeight": 700,
                    "letterSpacing": "0.12em",
                    "flexShrink": 0,
                    "marginRight": "10px",
                    "alignSelf": "center",
                },
            ),
            html.Div(
                buttons,
                style={"display": "flex", "gap": "3px", "flexWrap": "wrap"},
            ),
            dcc.Store(id=f"{id_prefix}-period-store", data=default),
        ],
        style={
            "display": "flex",
            "alignItems": "center",
            "padding": "6px 14px",
            "marginBottom": "10px",
            "backgroundColor": "#0a0a0a",
            "border": "1px solid #1e1e1e",
            "borderRadius": "4px",
            "flexWrap": "wrap",
            "gap": "6px",
        },
    )
