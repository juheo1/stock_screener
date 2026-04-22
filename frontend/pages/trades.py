"""
frontend.pages.trades
=====================
Trade Tracker page — view, edit, and manage tracked scanner signals.

Layout
------
1. Header + view-filter tabs (All / Open / Closed / Skipped)
2. Controls bar: Add Trade, Export CSV, Import CSV, Refresh
3. Import panel (collapsible)
4. Editable AG Grid
5. Add-Trade modal
"""
from __future__ import annotations

import base64
import csv
import io
import json
import logging

import dash
import dash_ag_grid as dag
import dash_bootstrap_components as dbc
from dash import (
    Input,
    Output,
    State,
    callback,
    dcc,
    html,
    no_update,
)

from frontend.api_client import (
    trades_create,
    trades_delete,
    trades_import,
    trades_import_brokerage,
    trades_list,
    trades_list_strategies,
    trades_update,
)
from frontend.config import API_BASE_URL

logger = logging.getLogger(__name__)

dash.register_page(__name__, path="/trades", title="Trade Tracker")

# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

_BG       = "#0a0a0a"
_CARD     = "#111111"
_BORDER   = "#1e1e1e"
_TEXT     = "#e0e0e0"
_MUTED    = "#666666"
_GREEN    = "#00c896"
_RED      = "#ff4444"
_YELLOW   = "#f0c040"
_BLUE     = "#4a9eff"

_card_style = {
    "backgroundColor": _CARD,
    "border": f"1px solid {_BORDER}",
    "borderRadius": "6px",
    "padding": "12px",
    "marginBottom": "12px",
}

_btn_sm = {"size": "sm", "style": {"marginRight": "6px", "marginBottom": "4px"}}

# ---------------------------------------------------------------------------
# Column definitions
# ---------------------------------------------------------------------------

_SIGNAL_COLS = [
    {"field": "ticker",               "headerName": "Ticker",      "width": 90,  "pinned": "left",
     "cellStyle": {"color": "#ffffff", "fontWeight": 700}},
    {"field": "signal_side_str",      "headerName": "Side",        "width": 70,
     "cellRenderer": "agAnimateShowChangeCellRenderer"},
    {"field": "strategy_display_name","headerName": "Strategy",    "width": 160, "filter": True,
     "editable": True, "cellEditor": "agSelectCellEditor",
     "cellEditorParams": {"values": ["Manual / Brokerage Import"]}},
    {"field": "signal_date",          "headerName": "Signal Date", "width": 110},
    {"field": "sell_signal_active",   "headerName": "Sell Signal?","width": 110},
    {"field": "latest_signal_date",   "headerName": "Sig Check Date","width": 115},
    {"field": "close_price",          "headerName": "Signal Close","width": 100,
     "valueFormatter": {"function": "params.value != null ? '$' + params.value.toFixed(2) : '—'"}},
    {"field": "bt_win_rate_pct",      "headerName": "Win %",       "width": 80,
     "valueFormatter": {"function": "params.value != null ? params.value.toFixed(1) + '%' : '—'"}},
    {"field": "bt_trade_count",       "headerName": "BT Trades",   "width": 80},
    {"field": "source_etfs_str",      "headerName": "ETFs",        "flex": 1},
]

_EXEC_COLS = [
    {"field": "execution_status",   "headerName": "Status",      "width": 110, "editable": True,
     "cellEditor": "agSelectCellEditor",
     "cellEditorParams": {"values": ["TRACKED","ENTERED","PARTIAL","EXITED","SKIPPED","CANCELLED"]},
     "filter": True},
    {"field": "planned_action",     "headerName": "Planned",     "width": 90,  "editable": True,
     "cellEditor": "agSelectCellEditor",
     "cellEditorParams": {"values": ["", "BUY","SELL","SHORT","COVER"]}},
    {"field": "actual_entry_date",  "headerName": "Entry Date",  "width": 110, "editable": True,
     "cellEditor": "agTextCellEditor"},
    {"field": "actual_entry_price", "headerName": "Entry Price", "width": 100, "editable": True,
     "cellEditor": "agNumberCellEditor",
     "valueFormatter": {"function": "params.value != null ? '$' + params.value.toFixed(2) : '—'"}},
    {"field": "actual_exit_date",   "headerName": "Exit Date",   "width": 110, "editable": True,
     "cellEditor": "agTextCellEditor"},
    {"field": "actual_exit_price",  "headerName": "Exit Price",  "width": 100, "editable": True,
     "cellEditor": "agNumberCellEditor",
     "valueFormatter": {"function": "params.value != null ? '$' + params.value.toFixed(2) : '—'"}},
    {"field": "quantity",           "headerName": "Qty",         "width": 80,  "editable": True,
     "cellEditor": "agNumberCellEditor"},
    {"field": "notes",              "headerName": "Notes",       "width": 150, "editable": True,
     "cellEditor": "agLargeTextCellEditor"},
    {"field": "tags",               "headerName": "Tags",        "width": 120, "editable": True,
     "cellEditor": "agTextCellEditor"},
]

_DERIVED_COLS = [
    {"field": "slippage",            "headerName": "Slip",        "width": 80,
     "valueFormatter": {"function": "params.value != null ? (params.value >= 0 ? '+' : '') + params.value.toFixed(2) : '—'"}},
    {"field": "slippage_pct",        "headerName": "Slip %",      "width": 80,
     "valueFormatter": {"function": "params.value != null ? (params.value >= 0 ? '+' : '') + params.value.toFixed(1) + '%' : '—'"}},
    {"field": "holding_period_days", "headerName": "Days",        "width": 70},
    {"field": "realized_pnl",        "headerName": "PnL",         "width": 90,
     "valueFormatter": {"function": "params.value != null ? (params.value >= 0 ? '+' : '') + params.value.toFixed(2) : '—'"}},
    {"field": "return_pct",          "headerName": "Return %",    "width": 90,
     "valueFormatter": {"function": "params.value != null ? (params.value >= 0 ? '+' : '') + params.value.toFixed(1) + '%' : '—'"}},
    {"field": "win_flag_str",        "headerName": "W/L",         "width": 60},
    {"field": "execution_timing",    "headerName": "Timing",      "width": 90},
]

ALL_COLS = _SIGNAL_COLS + _EXEC_COLS + _DERIVED_COLS


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def layout() -> html.Div:
    return html.Div(
        style={"backgroundColor": _BG, "minHeight": "100vh", "padding": "16px",
               "fontFamily": "'Inter', 'Segoe UI', system-ui, sans-serif"},
        children=[
            # Stores
            dcc.Store(id="trades-data-store"),
            dcc.Store(id="trades-view-filter", data="all"),
            dcc.Store(id="trades-delete-mode", data=False),
            dcc.Store(id="trades-undo-stack", data=[]),
            dcc.Store(id="trades-pending-delete-ids", data=[]),
            dcc.Store(id="trades-strategies-store", data=[]),
            dcc.Store(id="trades-brokerage-csv-store", data=None),

            # Header
            html.H4("Trade Tracker", style={"color": "#ffffff", "fontWeight": 700,
                                             "marginBottom": "12px"}),

            # View filters + controls bar
            html.Div(style={**_card_style, "padding": "8px 12px"}, children=[
                dbc.Row([
                    # View filter buttons
                    dbc.Col([
                        dbc.ButtonGroup([
                            dbc.Button("All",     id="trades-filter-all",    color="primary",
                                       outline=False, size="sm"),
                            dbc.Button("Open",    id="trades-filter-open",   color="secondary",
                                       outline=True,  size="sm"),
                            dbc.Button("Closed",  id="trades-filter-closed", color="secondary",
                                       outline=True,  size="sm"),
                            dbc.Button("Skipped", id="trades-filter-skipped",color="secondary",
                                       outline=True,  size="sm"),
                        ], style={"marginRight": "16px"}),
                    ], width="auto"),
                    # Action buttons
                    dbc.Col([
                        dbc.Button("+ Add Trade",  id="trades-add-btn",    color="success",
                                   size="sm", style={"marginRight": "6px"}),
                        html.A(
                            dbc.Button("Export CSV", color="info", size="sm",
                                       style={"marginRight": "6px"}),
                            href=f"{API_BASE_URL}/api/trades/export",
                            target="_blank",
                        ),
                        dbc.Button("Import CSV",   id="trades-import-toggle", color="secondary",
                                   size="sm", outline=True, style={"marginRight": "6px"}),
                        dbc.Button("Brokerage Import", id="trades-brokerage-import-toggle",
                                   color="info", size="sm", outline=True,
                                   style={"marginRight": "6px"}),
                        dbc.Button("⟳ Refresh",    id="trades-refresh-btn", color="secondary",
                                   size="sm", outline=True, style={"marginRight": "6px"}),
                        dbc.Button(
                            "Delete Mode", id="trades-delete-mode-btn",
                            color="danger", size="sm", outline=True,
                            style={"marginRight": "6px"},
                        ),
                        dbc.Button(
                            "Check Signals", id="trades-check-signals-btn",
                            color="warning", size="sm", outline=True,
                        ),
                    ], width="auto", style={"marginLeft": "auto"}),
                ], align="center"),
            ]),

            # Import panel (collapsible)
            dbc.Collapse(
                id="trades-import-panel",
                is_open=False,
                children=[
                    html.Div(style=_card_style, children=[
                        html.Div("IMPORT CSV", style={"color": _MUTED, "fontSize": "0.75rem",
                                                       "letterSpacing": "1px", "marginBottom": "8px"}),
                        dcc.Upload(
                            id="trades-upload",
                            children=html.Div([
                                "Drag & drop a CSV file here, or ",
                                html.A("click to browse", style={"color": _BLUE, "cursor": "pointer"}),
                                html.Br(),
                                html.Small("Required columns: ticker, signal_date, strategy_slug (or strategy)",
                                           style={"color": _MUTED}),
                            ]),
                            style={
                                "width": "100%", "height": "80px",
                                "lineHeight": "normal", "borderWidth": "1px",
                                "borderStyle": "dashed", "borderRadius": "5px",
                                "borderColor": _BORDER, "textAlign": "center",
                                "display": "flex", "alignItems": "center",
                                "justifyContent": "center", "color": _TEXT,
                                "cursor": "pointer",
                            },
                            multiple=False,
                        ),
                        html.Div(id="trades-import-feedback", style={"marginTop": "8px"}),
                    ]),
                ],
            ),

            # Brokerage import panel (collapsible)
            dbc.Collapse(
                id="trades-brokerage-import-panel",
                is_open=False,
                children=[
                    html.Div(style=_card_style, children=[
                        html.Div("IMPORT FROM BROKERAGE",
                                 style={"color": _MUTED, "fontSize": "0.75rem",
                                        "letterSpacing": "1px", "marginBottom": "8px"}),
                        dcc.Upload(
                            id="trades-brokerage-upload",
                            children=html.Div([
                                "Drag & drop your brokerage CSV here, or ",
                                html.A("click to browse",
                                       style={"color": _BLUE, "cursor": "pointer"}),
                                html.Br(),
                                html.Small("Supported: Schwab, Fidelity, Vanguard",
                                           style={"color": _MUTED}),
                            ]),
                            style={
                                "width": "100%", "height": "80px",
                                "lineHeight": "normal", "borderWidth": "1px",
                                "borderStyle": "dashed", "borderRadius": "5px",
                                "borderColor": _BORDER, "textAlign": "center",
                                "display": "flex", "alignItems": "center",
                                "justifyContent": "center", "color": _TEXT,
                                "cursor": "pointer",
                            },
                            multiple=False,
                        ),
                        html.Div(id="trades-brokerage-detected",
                                 style={"marginTop": "8px", "color": _MUTED,
                                        "fontSize": "0.8rem"}),
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Brokerage", style={"fontSize": "0.8rem",
                                                               "color": _MUTED}),
                                dbc.Select(
                                    id="trades-brokerage-select",
                                    options=[
                                        {"label": "Auto-detect", "value": "auto"},
                                        {"label": "Charles Schwab", "value": "schwab"},
                                        {"label": "Fidelity", "value": "fidelity"},
                                        {"label": "Vanguard", "value": "vanguard"},
                                    ],
                                    value="auto",
                                    size="sm",
                                ),
                            ], width=3),
                            dbc.Col([
                                dbc.Label("Assign Strategy", style={"fontSize": "0.8rem",
                                                                      "color": _MUTED}),
                                dbc.Select(
                                    id="trades-brokerage-strategy-select",
                                    options=[{"label": "Manual / Brokerage Import",
                                              "value": "manual"}],
                                    value="manual",
                                    size="sm",
                                ),
                            ], width=4),
                            dbc.Col([
                                dbc.Label("\u00a0", style={"fontSize": "0.8rem"}),
                                html.Br(),
                                dbc.Button("Import", id="trades-brokerage-import-btn",
                                           color="success", size="sm"),
                            ], width=2),
                        ], style={"marginTop": "10px"}),
                        # Preview table
                        html.Div(id="trades-brokerage-preview", style={"marginTop": "10px"}),
                        # Result feedback
                        html.Div(id="trades-brokerage-feedback", style={"marginTop": "8px"}),
                    ]),
                ],
            ),

            # Status bar
            html.Div(id="trades-status-bar", style={"marginBottom": "8px",
                                                      "color": _MUTED, "fontSize": "0.8rem"}),

            # Main AG Grid
            html.Div(style=_card_style, children=[
                dag.AgGrid(
                    id="trades-grid",
                    rowData=[],
                    columnDefs=ALL_COLS,
                    defaultColDef={
                        "resizable": True,
                        "sortable": True,
                        "filter": False,
                        "suppressMovable": False,
                    },
                    dashGridOptions={
                        "rowSelection": "single",
                        "undoRedoCellEditing": True,
                        "singleClickEdit": False,
                        "stopEditingWhenCellsLoseFocus": True,
                        "animateRows": True,
                        "suppressRowClickSelection": False,
                    },
                    style={"height": "600px"},
                    className="ag-theme-alpine-dark",
                ),
            ]),

            # Floating delete action bar
            html.Div(
                id="trades-delete-bar",
                style={
                    "display": "none",
                    "position": "fixed", "bottom": "20px", "left": "50%",
                    "transform": "translateX(-50%)", "zIndex": 1000,
                    "backgroundColor": "#1e1e1e", "border": f"1px solid {_RED}",
                    "borderRadius": "8px", "padding": "12px 24px",
                    "boxShadow": "0 4px 20px rgba(0,0,0,0.6)",
                },
                children=[
                    html.Span(id="trades-delete-count-text",
                              style={"color": _TEXT, "fontSize": "0.9rem"}),
                    dbc.Button("Confirm Delete", id="trades-confirm-delete-btn",
                               color="danger", size="sm"),
                    dbc.Button("Cancel", id="trades-cancel-delete-btn",
                               color="secondary", size="sm", outline=True),
                ],
            ),

            # Undo toast
            dbc.Toast(
                id="trades-undo-toast",
                header="Trades Deleted",
                is_open=False,
                dismissable=True,
                duration=10000,
                style={"position": "fixed", "bottom": "20px", "right": "20px",
                       "zIndex": 999, "minWidth": "280px",
                       "backgroundColor": "#1e1e1e", "border": f"1px solid {_BORDER}"},
                children=[
                    html.Div([
                        html.Span(id="trades-undo-toast-msg",
                                  style={"color": _TEXT, "marginRight": "12px"}),
                        dbc.Button("Undo", id="trades-undo-btn",
                                   color="warning", size="sm", outline=True),
                    ], style={"display": "flex", "alignItems": "center"}),
                ],
            ),

            # Add Trade modal
            dbc.Modal(
                id="trades-add-modal",
                is_open=False,
                size="lg",
                children=[
                    dbc.ModalHeader(dbc.ModalTitle("Add Manual Trade")),
                    dbc.ModalBody([
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Ticker *", style={"fontSize": "0.85rem"}),
                                dbc.Input(id="add-trade-ticker", placeholder="e.g. AAPL",
                                          size="sm"),
                            ], width=3),
                            dbc.Col([
                                dbc.Label("Signal Side *", style={"fontSize": "0.85rem"}),
                                dbc.Select(id="add-trade-signal-side", size="sm",
                                           options=[{"label": "BUY", "value": "1"},
                                                    {"label": "SELL", "value": "-1"}],
                                           value="1"),
                            ], width=3),
                            dbc.Col([
                                dbc.Label("Strategy *", style={"fontSize": "0.85rem"}),
                                dbc.Input(id="add-trade-strategy", placeholder="strategy_slug",
                                          size="sm"),
                            ], width=3),
                            dbc.Col([
                                dbc.Label("Signal Date *", style={"fontSize": "0.85rem"}),
                                dbc.Input(id="add-trade-signal-date", placeholder="YYYY-MM-DD",
                                          size="sm"),
                            ], width=3),
                        ], className="mb-2"),
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Scan Date", style={"fontSize": "0.85rem"}),
                                dbc.Input(id="add-trade-scan-date", placeholder="YYYY-MM-DD",
                                          size="sm"),
                            ], width=3),
                            dbc.Col([
                                dbc.Label("Close Price", style={"fontSize": "0.85rem"}),
                                dbc.Input(id="add-trade-close-price", placeholder="0.00",
                                          type="number", size="sm"),
                            ], width=3),
                            dbc.Col([
                                dbc.Label("Notes", style={"fontSize": "0.85rem"}),
                                dbc.Input(id="add-trade-notes", placeholder="optional",
                                          size="sm"),
                            ], width=6),
                        ], className="mb-2"),
                        html.Div(id="add-trade-feedback"),
                    ]),
                    dbc.ModalFooter([
                        dbc.Button("Cancel", id="add-trade-cancel", color="secondary",
                                   size="sm", style={"marginRight": "6px"}),
                        dbc.Button("Add Trade", id="add-trade-submit", color="success", size="sm"),
                    ]),
                ],
            ),

            # Delete confirm modal
            dbc.Modal(
                id="trades-delete-confirm-modal",
                is_open=False,
                children=[
                    dbc.ModalHeader(dbc.ModalTitle("Confirm Delete")),
                    dbc.ModalBody(html.Div(id="trades-delete-modal-body")),
                    dbc.ModalFooter([
                        dbc.Button("Cancel", id="trades-delete-modal-cancel",
                                   color="secondary", size="sm",
                                   style={"marginRight": "6px"}),
                        dbc.Button("Delete", id="trades-delete-modal-confirm",
                                   color="danger", size="sm"),
                    ]),
                ],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _enrich_row(row: dict) -> dict:
    """Add display-only fields to a trade row dict."""
    side = row.get("signal_side", 1)
    row["signal_side_str"] = "BUY" if side == 1 else "SELL"

    etfs = row.get("source_etfs", [])
    row["source_etfs_str"] = ", ".join(etfs) if isinstance(etfs, list) else str(etfs)

    wr = row.get("bt_win_rate")
    row["bt_win_rate_pct"] = wr * 100 if wr is not None else None

    wf = row.get("win_flag")
    if wf == 1:
        row["win_flag_str"] = "W"
    elif wf == 0:
        row["win_flag_str"] = "L"
    else:
        row["win_flag_str"] = "—"

    row.setdefault("sell_signal_active", "—")
    row.setdefault("latest_signal_date", "")
    return row


def _load_trades(status_filter: str = "all") -> tuple[list[dict], str]:
    """Fetch trades from API and return (enriched rows, status text)."""
    api_status = None if status_filter == "all" else status_filter
    data = trades_list(status=api_status)
    if data is None:
        return [], "API unavailable"
    rows = [_enrich_row(t) for t in data.get("trades", [])]
    total = data.get("total", len(rows))
    return rows, f"{total} trade(s)"


# ---------------------------------------------------------------------------
# Callback: view filter button states
# ---------------------------------------------------------------------------

@callback(
    Output("trades-filter-all",    "color"),
    Output("trades-filter-all",    "outline"),
    Output("trades-filter-open",   "color"),
    Output("trades-filter-open",   "outline"),
    Output("trades-filter-closed", "color"),
    Output("trades-filter-closed", "outline"),
    Output("trades-filter-skipped","color"),
    Output("trades-filter-skipped","outline"),
    Output("trades-view-filter",   "data"),
    Input("trades-filter-all",     "n_clicks"),
    Input("trades-filter-open",    "n_clicks"),
    Input("trades-filter-closed",  "n_clicks"),
    Input("trades-filter-skipped", "n_clicks"),
    prevent_initial_call=False,
)
def update_filter_buttons(_a, _o, _c, _s):
    tid = dash.ctx.triggered_id or "trades-filter-all"
    mapping = {
        "trades-filter-all":     "all",
        "trades-filter-open":    "open",
        "trades-filter-closed":  "closed",
        "trades-filter-skipped": "skipped",
    }
    active = mapping.get(tid, "all")

    def _btn(key):
        is_active = (mapping[key] == active)
        return ("primary" if is_active else "secondary", not is_active)

    a_c, a_o = _btn("trades-filter-all")
    o_c, o_o = _btn("trades-filter-open")
    c_c, c_o = _btn("trades-filter-closed")
    s_c, s_o = _btn("trades-filter-skipped")
    return a_c, a_o, o_c, o_o, c_c, c_o, s_c, s_o, active


# ---------------------------------------------------------------------------
# Callback: load trades data
# ---------------------------------------------------------------------------

@callback(
    Output("trades-data-store", "data"),
    Output("trades-status-bar", "children"),
    Input("trades-view-filter", "data"),
    Input("trades-refresh-btn", "n_clicks"),
)
def load_trades(view_filter, _refresh):
    rows, status_text = _load_trades(view_filter or "all")
    return rows, status_text


@callback(
    Output("trades-grid", "rowData"),
    Input("trades-data-store", "data"),
)
def update_grid(data):
    return data or []




# ---------------------------------------------------------------------------
# Callback: toggle import panel
# ---------------------------------------------------------------------------

@callback(
    Output("trades-import-panel", "is_open"),
    Input("trades-import-toggle", "n_clicks"),
    State("trades-import-panel", "is_open"),
    prevent_initial_call=True,
)
def toggle_import_panel(n, is_open):
    return not is_open


# ---------------------------------------------------------------------------
# Callback: CSV import upload
# ---------------------------------------------------------------------------

@callback(
    Output("trades-import-feedback", "children"),
    Output("trades-data-store", "data", allow_duplicate=True),
    Input("trades-upload", "contents"),
    State("trades-upload", "filename"),
    State("trades-view-filter", "data"),
    prevent_initial_call=True,
)
def handle_csv_upload(contents, filename, view_filter):
    if contents is None:
        return no_update, no_update

    # Decode base64 content from dcc.Upload
    content_type, content_string = contents.split(",", 1)
    decoded = base64.b64decode(content_string).decode("utf-8", errors="replace")

    # Parse CSV
    reader = csv.DictReader(io.StringIO(decoded))
    rows = list(reader)

    if not rows:
        return html.Span("CSV is empty or invalid.", style={"color": _RED}), no_update

    result = trades_import(rows)
    if result is None:
        return html.Span("Import request failed.", style={"color": _RED}), no_update

    created = result.get("created", 0)
    skipped = result.get("skipped", 0)
    errors  = result.get("errors", [])

    summary = f"Imported: {created} created, {skipped} skipped."
    if errors:
        summary += f" {len(errors)} error(s): " + "; ".join(errors[:3])
        color = _YELLOW
    else:
        color = _GREEN

    refreshed_rows, _ = _load_trades(view_filter or "all")
    return html.Span(summary, style={"color": color}), refreshed_rows


# ---------------------------------------------------------------------------
# Callback: Add Trade modal
# ---------------------------------------------------------------------------

@callback(
    Output("trades-add-modal", "is_open"),
    Input("trades-add-btn",    "n_clicks"),
    Input("add-trade-cancel",  "n_clicks"),
    Input("add-trade-submit",  "n_clicks"),
    State("trades-add-modal",  "is_open"),
    prevent_initial_call=True,
)
def toggle_add_modal(add_click, cancel_click, submit_click, is_open):
    tid = dash.ctx.triggered_id
    if tid == "trades-add-btn":
        return True
    if tid in ("add-trade-cancel", "add-trade-submit"):
        return False
    return is_open


@callback(
    Output("add-trade-feedback",      "children"),
    Output("trades-data-store",       "data", allow_duplicate=True),
    Output("add-trade-ticker",        "value"),
    Output("add-trade-strategy",      "value"),
    Output("add-trade-signal-date",   "value"),
    Output("add-trade-scan-date",     "value"),
    Output("add-trade-notes",         "value"),
    Input("add-trade-submit",         "n_clicks"),
    State("add-trade-ticker",         "value"),
    State("add-trade-signal-side",    "value"),
    State("add-trade-strategy",       "value"),
    State("add-trade-signal-date",    "value"),
    State("add-trade-scan-date",      "value"),
    State("add-trade-close-price",    "value"),
    State("add-trade-notes",          "value"),
    State("trades-view-filter",       "data"),
    prevent_initial_call=True,
)
def submit_add_trade(n, ticker, side, strategy, signal_date, scan_date,
                     close_price, notes, view_filter):
    if not n:
        return no_update, no_update, no_update, no_update, no_update, no_update, no_update

    # Validate required fields
    if not ticker or not strategy or not signal_date:
        msg = "Ticker, Strategy, and Signal Date are required."
        return html.Span(msg, style={"color": _RED}), no_update, no_update, no_update, no_update, no_update, no_update

    import datetime
    scan_date_val = scan_date or signal_date

    payload = {
        "ticker":           ticker.upper().strip(),
        "signal_side":      int(side),
        "strategy_slug":    strategy.strip(),
        "signal_date":      signal_date.strip(),
        "scan_date":        scan_date_val.strip(),
        "signal_category":  "manual",
        "close_price":      float(close_price) if close_price else None,
        "notes":            notes or "",
    }

    result = trades_create(payload)
    if result is None:
        return (html.Span("Failed to create trade.", style={"color": _RED}),
                no_update, no_update, no_update, no_update, no_update, no_update)

    refreshed_rows, _ = _load_trades(view_filter or "all")
    return (
        html.Span(f"Trade added: {ticker.upper()} {('BUY' if int(side)==1 else 'SELL')}",
                  style={"color": _GREEN}),
        refreshed_rows,
        "", "", "", "", "",
    )


# ---------------------------------------------------------------------------
# Callback: toggle delete mode
# ---------------------------------------------------------------------------

@callback(
    Output("trades-delete-mode", "data"),
    Output("trades-delete-mode-btn", "outline"),
    Output("trades-delete-mode-btn", "color"),
    Input("trades-delete-mode-btn", "n_clicks"),
    Input("trades-cancel-delete-btn", "n_clicks"),
    State("trades-delete-mode", "data"),
    prevent_initial_call=True,
)
def toggle_delete_mode(_toggle, _cancel, is_active):
    tid = dash.ctx.triggered_id
    if tid == "trades-cancel-delete-btn":
        return False, True, "danger"
    new_active = not is_active
    return new_active, not new_active, "danger"


@callback(
    Output("trades-grid", "dashGridOptions"),
    Output("trades-grid", "columnDefs"),
    Input("trades-delete-mode", "data"),
)
def update_grid_for_delete_mode(is_active):
    options = {
        "rowSelection": "multiple" if is_active else "single",
        "undoRedoCellEditing": True,
        "singleClickEdit": False,
        "stopEditingWhenCellsLoseFocus": True,
        "animateRows": True,
        "suppressRowClickSelection": False,
    }
    if is_active:
        checkbox_col = {
            "field": "_select", "headerName": "", "width": 50,
            "pinned": "left", "checkboxSelection": True,
            "headerCheckboxSelection": True, "suppressMenu": True,
            "sortable": False, "filter": False, "resizable": False,
        }
        cols = [checkbox_col] + ALL_COLS
    else:
        cols = ALL_COLS
    return options, cols


# ---------------------------------------------------------------------------
# Callback: show/hide floating delete bar
# ---------------------------------------------------------------------------

@callback(
    Output("trades-delete-bar", "style"),
    Output("trades-delete-count-text", "children"),
    Input("trades-grid", "selectedRows"),
    Input("trades-delete-mode", "data"),
)
def update_delete_bar(selected_rows, is_active):
    _hidden  = {"display": "none"}
    _visible = {
        "display": "flex", "alignItems": "center", "gap": "12px",
        "position": "fixed", "bottom": "20px", "left": "50%",
        "transform": "translateX(-50%)", "zIndex": 1000,
        "backgroundColor": "#1e1e1e", "border": f"1px solid {_RED}",
        "borderRadius": "8px", "padding": "12px 24px",
        "boxShadow": "0 4px 20px rgba(0,0,0,0.6)",
    }
    if not is_active or not selected_rows:
        return _hidden, ""
    n = len(selected_rows)
    return _visible, f"{n} trade(s) selected for deletion"


# ---------------------------------------------------------------------------
# Callback: open delete confirm modal
# ---------------------------------------------------------------------------

@callback(
    Output("trades-delete-confirm-modal", "is_open"),
    Output("trades-delete-modal-body", "children"),
    Output("trades-pending-delete-ids", "data"),
    Input("trades-confirm-delete-btn", "n_clicks"),
    Input("trades-delete-modal-cancel", "n_clicks"),
    Input("trades-delete-modal-confirm", "n_clicks"),
    State("trades-grid", "selectedRows"),
    State("trades-delete-confirm-modal", "is_open"),
    prevent_initial_call=True,
)
def manage_delete_modal(confirm_n, cancel_n, execute_n, selected_rows, is_open):
    tid = dash.ctx.triggered_id
    if tid == "trades-confirm-delete-btn":
        if not selected_rows:
            return no_update, no_update, no_update
        n = len(selected_rows)
        ids = [r.get("id") for r in selected_rows if r.get("id")]
        body = f"Delete {n} trade(s)? This can be undone via the Undo button."
        return True, body, ids
    if tid in ("trades-delete-modal-cancel", "trades-delete-modal-confirm"):
        return False, no_update, no_update
    return no_update, no_update, no_update


# ---------------------------------------------------------------------------
# Callback: execute delete + update undo stack
# ---------------------------------------------------------------------------

@callback(
    Output("trades-data-store", "data", allow_duplicate=True),
    Output("trades-status-bar", "children", allow_duplicate=True),
    Output("trades-undo-stack", "data"),
    Output("trades-undo-toast", "is_open"),
    Output("trades-undo-toast-msg", "children"),
    Output("trades-delete-mode", "data", allow_duplicate=True),
    Input("trades-delete-modal-confirm", "n_clicks"),
    State("trades-pending-delete-ids", "data"),
    State("trades-grid", "rowData"),
    State("trades-undo-stack", "data"),
    State("trades-view-filter", "data"),
    prevent_initial_call=True,
)
def execute_delete(n, ids_to_delete, row_data, undo_stack, view_filter):
    if not n or not ids_to_delete:
        return no_update, no_update, no_update, no_update, no_update, no_update

    id_set = set(ids_to_delete)
    deleted_rows = [r for r in (row_data or []) if r.get("id") in id_set]

    success_count = 0
    for trade_id in ids_to_delete:
        if trades_delete(trade_id):
            success_count += 1

    # Push deleted rows to undo stack (keep last 5 batches)
    new_stack = list(undo_stack or [])
    if deleted_rows:
        new_stack.append(deleted_rows)
        new_stack = new_stack[-5:]

    rows, status_text = _load_trades(view_filter or "all")
    toast_msg = f"Deleted {success_count} trade(s)."
    return rows, status_text, new_stack, True, toast_msg, False


# ---------------------------------------------------------------------------
# Callback: undo last delete
# ---------------------------------------------------------------------------

@callback(
    Output("trades-data-store", "data", allow_duplicate=True),
    Output("trades-status-bar", "children", allow_duplicate=True),
    Output("trades-undo-stack", "data", allow_duplicate=True),
    Output("trades-undo-toast", "is_open", allow_duplicate=True),
    Input("trades-undo-btn", "n_clicks"),
    State("trades-undo-stack", "data"),
    State("trades-view-filter", "data"),
    prevent_initial_call=True,
)
def undo_delete(n, undo_stack, view_filter):
    if not n or not undo_stack:
        return no_update, no_update, no_update, no_update

    last_batch = undo_stack[-1]
    new_stack  = undo_stack[:-1]

    for trade in last_batch:
        payload = {
            k: trade.get(k)
            for k in ("ticker", "signal_side", "strategy_slug", "signal_date",
                      "scan_date", "signal_category", "close_price", "notes",
                      "planned_action", "actual_entry_date", "actual_entry_price",
                      "actual_exit_date", "actual_exit_price", "quantity", "tags",
                      "execution_status")
            if trade.get(k) is not None
        }
        if not payload.get("ticker") or not payload.get("strategy_slug"):
            continue
        trades_create(payload)

    rows, status_text = _load_trades(view_filter or "all")
    return rows, status_text, new_stack, False


# ---------------------------------------------------------------------------
# Callback: check sell signals
# ---------------------------------------------------------------------------

@callback(
    Output("trades-data-store", "data", allow_duplicate=True),
    Output("trades-status-bar", "children", allow_duplicate=True),
    Input("trades-check-signals-btn", "n_clicks"),
    State("trades-data-store", "data"),
    State("trades-view-filter", "data"),
    prevent_initial_call=True,
)
def check_sell_signals(n_clicks, current_data, view_filter):
    if not n_clicks or not current_data:
        return no_update, no_update

    from frontend.strategy.data import fetch_ohlcv
    from frontend.strategy.engine import (
        load_strategy, run_strategy, StrategyError,
    )
    from frontend.strategy.data import get_source, compute_ma, compute_indicator

    # Only check TRACKED/ENTERED/PARTIAL BUY trades
    open_statuses = {"TRACKED", "ENTERED", "PARTIAL"}
    candidates = [
        r for r in current_data
        if r.get("signal_side", 1) == 1
        and r.get("execution_status", "TRACKED") in open_statuses
        and r.get("strategy_slug")
    ]

    signal_map: dict[int, dict] = {}

    import datetime as _dt
    _today = _dt.date.today()

    for trade in candidates:
        ticker   = trade.get("ticker", "")
        slug     = trade.get("strategy_slug", "")
        trade_id = trade.get("id")
        if not ticker or not slug or not trade_id:
            continue
        try:
            df = fetch_ohlcv(ticker, "1D")
            if df is None or df.empty:
                continue

            # Drop today's incomplete bar when market is still open.
            # yfinance includes the current partial session as the last row
            # on trading days before 4 pm ET; running signals on it produces
            # unreliable results and shows today as the check date.
            try:
                last_bar_date = df.index[-1].date()
            except AttributeError:
                last_bar_date = pd.Timestamp(df.index[-1]).date()
            if last_bar_date >= _today:
                df = df.iloc[:-1]

            if df.empty:
                continue

            # Try user strategy first, then fall back to built-ins.
            try:
                mod = load_strategy(slug)
            except StrategyError:
                mod = load_strategy(slug, is_builtin=True)

            result = run_strategy(
                df=df, ticker=ticker, interval="1D",
                strategy_module=mod, params={},
                get_source_fn=get_source,
                compute_ma_fn=compute_ma,
                compute_indicator_fn=compute_indicator,
            )
            last_sig  = int(result.signals.iloc[-1])
            last_date = str(df.index[-1])[:10]
            signal_map[trade_id] = {
                "sell_signal_active": "YES" if last_sig == -1 else "NO",
                "latest_signal_date": last_date,
            }
        except (StrategyError, Exception):
            signal_map[trade_id] = {
                "sell_signal_active": "—",
                "latest_signal_date": "error",
            }

    # Merge signal results into the current data
    updated = []
    for row in current_data:
        row = dict(row)
        trade_id = row.get("id")
        if trade_id in signal_map:
            row.update(signal_map[trade_id])
        else:
            row.setdefault("sell_signal_active", "—")
            row.setdefault("latest_signal_date", "")
        updated.append(row)

    checked = len(signal_map)
    status = f"Signal check complete: {checked} trade(s) checked."
    return updated, html.Span(status, style={"color": _GREEN})


# ---------------------------------------------------------------------------
# Callback: load strategies into store + populate brokerage strategy dropdown
# ---------------------------------------------------------------------------

@callback(
    Output("trades-strategies-store", "data"),
    Output("trades-brokerage-strategy-select", "options"),
    Output("trades-grid", "columnDefs", allow_duplicate=True),
    Input("trades-refresh-btn", "n_clicks"),
    Input("trades-brokerage-import-panel", "is_open"),
    prevent_initial_call="initial_duplicate",
)
def load_strategies(_refresh, _panel_open):
    strategies = trades_list_strategies()
    options = [{"label": s["display_name"], "value": s["slug"]} for s in strategies]
    display_names = [s["display_name"] for s in strategies]

    # Rebuild column defs with the updated strategy dropdown values
    updated_signal_cols = [
        col if col["field"] != "strategy_display_name"
        else {**col, "cellEditorParams": {"values": display_names}}
        for col in _SIGNAL_COLS
    ]
    cols = updated_signal_cols + _EXEC_COLS + _DERIVED_COLS
    return strategies, options, cols


# ---------------------------------------------------------------------------
# Callback: toggle brokerage import panel
# ---------------------------------------------------------------------------

@callback(
    Output("trades-brokerage-import-panel", "is_open"),
    Input("trades-brokerage-import-toggle", "n_clicks"),
    State("trades-brokerage-import-panel", "is_open"),
    prevent_initial_call=True,
)
def toggle_brokerage_panel(n, is_open):
    return not is_open


# ---------------------------------------------------------------------------
# Callback: brokerage CSV upload → detect + preview
# ---------------------------------------------------------------------------

@callback(
    Output("trades-brokerage-csv-store", "data"),
    Output("trades-brokerage-detected", "children"),
    Output("trades-brokerage-preview", "children"),
    Output("trades-brokerage-select", "value"),
    Input("trades-brokerage-upload", "contents"),
    State("trades-brokerage-upload", "filename"),
    prevent_initial_call=True,
)
def handle_brokerage_upload(contents, filename):
    if contents is None:
        return None, "", None, "auto"

    content_type, content_string = contents.split(",", 1)
    csv_text = base64.b64decode(content_string).decode("utf-8", errors="replace")

    from src.trade_tracker.brokerage_import import detect_brokerage, parse_positions

    detected = detect_brokerage(csv_text)

    detected_label = {
        "schwab": "Charles Schwab",
        "fidelity": "Fidelity",
        "vanguard": "Vanguard",
        "unknown": "Unknown (select manually)",
    }.get(detected, detected.title())

    detected_msg = html.Span(
        f"File: {filename}  |  Detected: {detected_label}",
        style={"color": _MUTED, "fontSize": "0.8rem"},
    )

    # Build preview (first 5 rows)
    preview_table = None
    if detected != "unknown":
        try:
            positions = parse_positions(detected, csv_text)[:5]
            if positions:
                preview_table = html.Div([
                    html.Div("Preview (first 5 rows):",
                             style={"color": _MUTED, "fontSize": "0.75rem",
                                    "marginBottom": "4px"}),
                    html.Table(
                        [
                            html.Thead(html.Tr([
                                html.Th("Ticker", style={"padding": "4px 8px"}),
                                html.Th("Qty",    style={"padding": "4px 8px"}),
                                html.Th("Entry Price", style={"padding": "4px 8px"}),
                                html.Th("Asset Type", style={"padding": "4px 8px"}),
                            ], style={"color": _MUTED, "fontSize": "0.75rem"})),
                            html.Tbody([
                                html.Tr([
                                    html.Td(p.ticker,
                                            style={"padding": "4px 8px", "color": "#fff",
                                                   "fontWeight": 700}),
                                    html.Td(f"{p.quantity:,.4f}",
                                            style={"padding": "4px 8px", "color": _TEXT}),
                                    html.Td(f"${p.entry_price:,.2f}",
                                            style={"padding": "4px 8px", "color": _TEXT}),
                                    html.Td(p.asset_type,
                                            style={"padding": "4px 8px", "color": _TEXT}),
                                ])
                                for p in positions
                            ]),
                        ],
                        style={"width": "100%", "borderCollapse": "collapse",
                               "backgroundColor": "#0d0d0d", "borderRadius": "4px",
                               "fontSize": "0.8rem"},
                    ),
                ])
        except Exception as exc:
            preview_table = html.Span(f"Preview error: {exc}", style={"color": _YELLOW})

    return csv_text, detected_msg, preview_table, detected if detected != "unknown" else "auto"


# ---------------------------------------------------------------------------
# Callback: run brokerage import
# ---------------------------------------------------------------------------

@callback(
    Output("trades-brokerage-feedback", "children"),
    Output("trades-data-store", "data", allow_duplicate=True),
    Input("trades-brokerage-import-btn", "n_clicks"),
    State("trades-brokerage-csv-store", "data"),
    State("trades-brokerage-select", "value"),
    State("trades-brokerage-strategy-select", "value"),
    State("trades-strategies-store", "data"),
    State("trades-view-filter", "data"),
    prevent_initial_call=True,
)
def run_brokerage_import(n, csv_text, brokerage, strategy_slug, strategies, view_filter):
    if not n or not csv_text:
        return html.Span("No file uploaded.", style={"color": _RED}), no_update

    # Resolve display name from slug
    strategy_display_name = "Manual / Brokerage Import"
    for s in (strategies or []):
        if s.get("slug") == strategy_slug:
            strategy_display_name = s.get("display_name", strategy_display_name)
            break

    result = trades_import_brokerage(
        brokerage=brokerage or "auto",
        csv_text=csv_text,
        strategy_slug=strategy_slug or "manual",
        strategy_display_name=strategy_display_name,
    )
    if result is None:
        return html.Span("Import request failed.", style={"color": _RED}), no_update

    detected = result.get("brokerage_detected", brokerage or "auto")
    created  = result.get("created", 0)
    updated  = result.get("updated", 0)
    skipped  = result.get("skipped", 0)
    errors   = result.get("errors", [])

    summary = (
        f"Imported from {detected.title()}: "
        f"{created} new, {updated} updated, {skipped} skipped."
    )
    if errors:
        summary += f"  {len(errors)} error(s): " + "; ".join(errors[:3])
        color = _YELLOW
    else:
        color = _GREEN

    refreshed_rows, _ = _load_trades(view_filter or "all")
    return html.Span(summary, style={"color": color}), refreshed_rows


# ---------------------------------------------------------------------------
# Callback: Strategy cell edit → PATCH with slug lookup
# ---------------------------------------------------------------------------

@callback(
    Output("trades-data-store", "data", allow_duplicate=True),
    Output("trades-status-bar", "children", allow_duplicate=True),
    Input("trades-grid", "cellValueChanged"),
    State("trades-view-filter", "data"),
    State("trades-strategies-store", "data"),
    prevent_initial_call=True,
)
def on_cell_edit_strategy(changed, view_filter, strategies):
    """Handle cell edits — for the strategy column, map display_name → slug."""
    if not changed:
        return no_update, no_update

    row = changed[0].get("data", {})
    trade_id = row.get("id")
    col_id = changed[0].get("colId")
    new_val = changed[0].get("value")

    if not trade_id or not col_id:
        return no_update, no_update

    if col_id == "strategy_display_name":
        # Map display name back to slug
        slug = "manual"
        for s in (strategies or []):
            if s.get("display_name") == new_val:
                slug = s.get("slug", "manual")
                break
        payload = {"strategy_display_name": new_val, "strategy_slug": slug}
    else:
        payload = {col_id: new_val}

    result = trades_update(trade_id, payload)
    if result is None:
        return no_update, html.Span("Update failed", style={"color": _RED})

    rows, status_text = _load_trades(view_filter or "all")
    return rows, status_text
