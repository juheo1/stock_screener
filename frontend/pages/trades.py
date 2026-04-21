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
    trades_list,
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
    {"field": "strategy_display_name","headerName": "Strategy",    "width": 160, "filter": True},
    {"field": "signal_date",          "headerName": "Signal Date", "width": 110},
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
                        dbc.Button("⟳ Refresh",    id="trades-refresh-btn", color="secondary",
                                   size="sm", outline=True),
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
                    },
                    style={"height": "600px"},
                    className="ag-theme-alpine-dark",
                ),
            ]),

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

            # Delete confirmation
            dcc.ConfirmDialog(
                id="trades-delete-confirm",
                message="Delete this trade? This cannot be undone.",
            ),
            dcc.Store(id="trades-delete-id-store"),
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
# Callback: cell edit → PATCH
# ---------------------------------------------------------------------------

@callback(
    Output("trades-data-store", "data", allow_duplicate=True),
    Output("trades-status-bar", "children", allow_duplicate=True),
    Input("trades-grid", "cellValueChanged"),
    State("trades-view-filter", "data"),
    prevent_initial_call=True,
)
def on_cell_edit(changed, view_filter):
    if not changed:
        return no_update, no_update

    row = changed[0].get("data", {})
    trade_id = row.get("id")
    col_id = changed[0].get("colId")
    new_val = changed[0].get("value")

    if not trade_id or not col_id:
        return no_update, no_update

    result = trades_update(trade_id, {col_id: new_val})
    if result is None:
        return no_update, html.Span("Update failed", style={"color": _RED})

    rows, status_text = _load_trades(view_filter or "all")
    return rows, status_text


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
