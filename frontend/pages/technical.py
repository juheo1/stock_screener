"""
frontend.pages.technical
========================
Technical Analysis – interactive candlestick chart with add/remove indicators.

Indicators are stored as a list in dcc.Store and rendered dynamically.
Each indicator has: id, type, color, params, style.
Supported types: SMA, EMA, BB, DC, VOLMA
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import dash
import dash_bootstrap_components as dbc
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dash import ALL, Input, Output, State, callback, ctx, dcc, html, no_update

from frontend.strategy.engine import (
    StrategyError,
    delete_user_strategy,
    get_chart_bundle,
    list_strategies,
    load_strategy,
    run_strategy,
    save_user_strategy,
)
from frontend.strategy.backtest import run_backtest, backtest_to_dict
from frontend.strategy.data import (
    INTERVAL_CFG as _INTERVAL_CFG,
    fetch_ohlcv as _fetch_ohlcv,
    get_source as _get_source,
    compute_ma as _compute_ma,
    compute_vol_stats as _compute_vol_stats,
    hex_to_rgba as _hex_to_rgba,
    compute_indicator as _compute_indicator,
    get_fb_curve as _get_fb_curve,
)

# ---------------------------------------------------------------------------
# Preset directory (server-side filesystem)
# ---------------------------------------------------------------------------

_PRESET_DIR = Path(__file__).resolve().parents[2] / "data" / "technical_chart"
_PRESET_DIR.mkdir(parents=True, exist_ok=True)


def _list_presets() -> list[str]:
    """Return sorted list of preset names (without .json extension)."""
    return sorted(p.stem for p in _PRESET_DIR.glob("*.json"))


def _load_preset(name: str) -> dict | None:
    """Read a preset JSON file by name. Returns None if not found."""
    path = _PRESET_DIR / f"{name}.json"
    if not path.is_file():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_preset(name: str, preset: dict) -> None:
    """Write a preset dict as JSON to the preset directory."""
    safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in name)
    path = _PRESET_DIR / f"{safe or 'preset'}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(preset, f, indent=2)


def _delete_preset(name: str) -> bool:
    """Delete a preset file. Returns True if deleted."""
    path = _PRESET_DIR / f"{name}.json"
    if path.is_file():
        path.unlink()
        return True
    return False


def _preset_dropdown_options() -> list[dict]:
    """Build dropdown options from preset files on disk."""
    return [{"label": n, "value": n} for n in _list_presets()]

dash.register_page(
    __name__,
    path="/technical",
    name="Technical Analysis",
    title="Technical Analysis",
)

# ---------------------------------------------------------------------------
# Interval config
# ---------------------------------------------------------------------------

_INTERVALS: list[tuple[str, str]] = [
    ("1m",  "1MIN"), ("2m",  "2MIN"), ("5m",  "5MIN"),
    ("15m", "15MIN"), ("30m", "30MIN"),
    ("1H",  "1H"),   ("2H",  "2H"),   ("3H",  "3H"),   ("4H",  "4H"),
    ("1D",  "1D"),   ("1W",  "1W"),
    ("1M",  "1MON"), ("3M",  "3MON"), ("6M",  "6MON"), ("12M", "12MON"),
]
_DEFAULT_IV = "1D"

_INTRADAY_IVS = {"1MIN", "2MIN", "5MIN", "15MIN", "30MIN", "1H", "2H", "3H", "4H"}
_DAILY_PLUS   = {"1D", "1W", "1MON", "3MON", "6MON", "12MON"}

# ---------------------------------------------------------------------------
# Indicator definitions
# ---------------------------------------------------------------------------

_MA_TYPES = ["SMA", "EMA", "WMA", "SMMA (RMA)", "VWMA"]
_SOURCES   = ["Close", "Open", "High", "Low", "HL2", "HLC3", "OHLC4"]

_IND_TYPES = {
    "SMA":   {"label": "SMA",             "desc": "Simple Moving Average"},
    "EMA":   {"label": "EMA",             "desc": "Exponential Moving Average"},
    "BB":    {"label": "Bollinger Bands", "desc": "Volatility bands around a moving average"},
    "DC":    {"label": "Donchian",        "desc": "Donchian Channel — highest high / lowest low"},
    "VOLMA": {"label": "Volume MA",       "desc": "Volume panel with moving average"},
}

_IND_DEFAULTS: dict[str, dict] = {
    "SMA":   {"period": 50,  "source": "Close"},
    "EMA":   {"period": 21,  "source": "Close"},
    "BB":    {"length": 20,  "ma_type": "SMA", "source": "Close",
              "stddev": 2.0, "offset": 0},
    "DC":    {"period": 20},
    "VOLMA": {"period": 20},
}

# Color cycling palette for auto-assignment
_IND_COLOR_POOL = [
    "#f0c040", "#40e0c0", "#f040a0", "#a07af0",
    "#f0a040", "#40a0f0", "#80f040", "#f07040",
    "#40f080", "#c040c0",
]

# 16-color style palette (themed + basic RGB)
_STYLE_COLORS = [
    {"label": "Gold",     "value": "#f0c040"},
    {"label": "Teal",     "value": "#40e0c0"},
    {"label": "Pink",     "value": "#f040a0"},
    {"label": "Purple",   "value": "#a07af0"},
    {"label": "Orange",   "value": "#f0a040"},
    {"label": "Sky Blue", "value": "#40a0f0"},
    {"label": "Lime",     "value": "#80f040"},
    {"label": "Coral",    "value": "#f07040"},
    {"label": "Red",      "value": "#ff4444"},
    {"label": "Green",    "value": "#44ff88"},
    {"label": "Blue",     "value": "#4488ff"},
    {"label": "Cyan",     "value": "#00ffff"},
    {"label": "Magenta",  "value": "#ff44ff"},
    {"label": "Yellow",   "value": "#ffff44"},
    {"label": "White",    "value": "#ffffff"},
    {"label": "Gray",     "value": "#888888"},
    {"label": "(None)",   "value": "none"},
]
_STYLE_COLOR_VALUES = [c["value"] for c in _STYLE_COLORS]


def _default_style(color: str) -> dict:
    return {
        "color_basis": color, "color_upper": color,
        "color_lower": color, "color_legend": color,
    }


def _majority_color(cb: str, cu: str, cl: str, fallback: str = "#888888") -> str:
    """Return the most common non-'none' color among basis/upper/lower; prefer cb on tie."""
    candidates = [c for c in [cb, cu, cl] if c and c != "none"]
    if not candidates:
        return fallback
    freq: dict[str, int] = {}
    for c in candidates:
        freq[c] = freq.get(c, 0) + 1
    max_count = max(freq.values())
    majority_opts = [c for c, n in freq.items() if n == max_count]
    return cb if (cb in majority_opts and cb != "none") else majority_opts[0]


_DEFAULT_INDICATORS: list[dict] = [
    {
        "id": "volma-init", "type": "VOLMA", "color": "#4a90e2",
        "params": {"period": 20},
        "style": _default_style("#4a90e2"),
    },
    {
        "id": "sma-init", "type": "SMA", "color": "#f0c040",
        "params": {"period": 50, "source": "Close"},
        "style": _default_style("#f0c040"),
    },
]

# ---------------------------------------------------------------------------
# Colour constants
# ---------------------------------------------------------------------------

_C_UP        = "#26a69a"
_C_DOWN      = "#ef5350"
_BG          = "#000000"
_GRID        = "#1c1c1c"
_AX          = "#666666"
_C_STRAT_BUY  = "#00e676"   # bright green  – buy marker
_C_STRAT_SELL = "#ff1744"   # vivid red     – sell marker
_MARKER_OFFSET = 0.005       # fraction above/below candle for signal triangles

# ---------------------------------------------------------------------------
# Label helpers
# ---------------------------------------------------------------------------

def _src_short(s: str) -> str:
    return {"Close": "C", "Open": "O", "High": "H", "Low": "L"}.get(s, s)


def _ind_short_label(ind: dict) -> str:
    """Short label for chip display."""
    t = ind["type"]; p = ind["params"]
    if t == "SMA":   return f"SMA {p.get('period', 50)}"
    if t == "EMA":   return f"EMA {p.get('period', 21)}"
    if t == "BB":    return f"BB({p.get('length',20)}, {p.get('stddev',2.0)})"
    if t == "DC":    return f"DC({p.get('period',20)})"
    if t == "VOLMA": return f"Vol MA({p.get('period',20)})"
    return t


def _ind_full_label(ind: dict) -> str:
    """Full label for legend and hover."""
    t = ind["type"]; p = ind["params"]
    src = _src_short(p.get("source", "Close"))
    if t == "SMA":   return f"SMA ({p.get('period',50)}, {src})"
    if t == "EMA":   return f"EMA ({p.get('period',21)}, {src})"
    if t == "BB":
        return (f"BB ({p.get('length',20)}, {p.get('ma_type','SMA')}, "
                f"{src}, {p.get('stddev',2.0)}, {p.get('offset',0)})")
    if t == "DC":    return f"DC ({p.get('period',20)})"
    if t == "VOLMA": return f"Vol MA ({p.get('period',20)})"
    return t

# ---------------------------------------------------------------------------
# Data helpers (imported from frontend.strategy.data)
# ---------------------------------------------------------------------------
# _fetch_ohlcv, _get_source, _compute_ma, _compute_vol_stats, _hex_to_rgba,
# _compute_indicator, _get_fb_curve are imported at the top of this file.


# ---------------------------------------------------------------------------
# Hover helpers
# ---------------------------------------------------------------------------

def _fmt_vol(v: float) -> str:
    if v >= 1e9: return f"{v/1e9:.2f}B"
    if v >= 1e6: return f"{v/1e6:.2f}M"
    if v >= 1e3: return f"{v/1e3:.1f}K"
    return f"{v:.0f}"


def _ordinal(n: int) -> str:
    n = int(n)
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return f"{n}{['th','st','nd','rd','th'][min(n % 10, 4)]}"


def _zscore_color(z: float) -> str:
    if z >= 2.5:  return "#ff3333"
    if z >= 1.5:  return "#ff8800"
    if z >= 0.5:  return "#88cc88"
    if z >= -0.5: return "#888888"
    if z >= -1.5: return "#4499ff"
    if z >= -2.5: return "#2266dd"
    return "#1144bb"


# ---------------------------------------------------------------------------
# Figure builder
# ---------------------------------------------------------------------------

def _build_figure(
    df: pd.DataFrame,
    ticker: str,
    interval_key: str,
    computed_inds: list[dict],
    fill_betweens: list[dict] | None = None,
    signals: "pd.Series | None" = None,
) -> go.Figure:

    vol_ind     = next((c for c in computed_inds if c["type"] == "VOLMA"), None)
    show_volume = vol_ind is not None
    n_rows      = 2 if show_volume else 1
    row_heights = [0.72, 0.28] if show_volume else [1.0]

    fig = make_subplots(
        rows=n_rows, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.018,
        row_heights=row_heights,
    )

    # ── Invisible hover probe ────────────────────────────────────────
    probe_custom = []
    for i, (o_, h_, l_, c_) in enumerate(
        zip(df["Open"], df["High"], df["Low"], df["Close"])
    ):
        o_, h_, l_, c_ = float(o_), float(h_), float(l_), float(c_)
        up  = c_ >= o_
        arr = "▲" if up else "▼"
        cc  = _C_UP if up else _C_DOWN
        probe_custom.append([i, (
            f"<span style='color:{_AX}'>O </span>"
            f"<span style='color:#cccccc'>{o_:.2f}</span>  "
            f"<span style='color:{_AX}'>H </span>"
            f"<span style='color:{_C_UP}'>{h_:.2f}</span>  "
            f"<span style='color:{_AX}'>L </span>"
            f"<span style='color:{_C_DOWN}'>{l_:.2f}</span>  "
            f"<span style='color:{_AX}'>C </span>"
            f"<span style='color:{cc}'>{arr} {c_:.2f}</span>"
        )])

    fig.add_trace(go.Scatter(
        x=df.index, y=df["High"], mode="lines",
        line=dict(color="rgba(0,0,0,0)", width=1),
        customdata=probe_custom,
        hovertemplate=(
            f"<b style='color:#ffffff'>{ticker}</b><br>%{{customdata[1]}}<extra></extra>"
        ),
        showlegend=False, name="",
    ), row=1, col=1)

    # ── Per-indicator price-panel traces ─────────────────────────────
    for ci in computed_inds:
        t     = ci["type"]
        style = ci.get("style", {})
        color = ci.get("color", "#888888")
        cb    = style.get("color_basis", color)   # basis / mid / line
        cu    = style.get("color_upper", color)   # upper
        cl    = style.get("color_lower", color)   # lower
        grp   = ci["id"]
        lbl   = ci["full_label"]

        if t == "SMA":
            if cb != "none":
                fig.add_trace(go.Scatter(
                    x=df.index, y=ci["values"], mode="lines",
                    name=lbl, legendgroup=grp,
                    showlegend=True,
                    line=dict(color=cb, width=1.5),
                    hoverinfo="skip",
                ), row=1, col=1)

        elif t == "EMA":
            if cb != "none":
                fig.add_trace(go.Scatter(
                    x=df.index, y=ci["values"], mode="lines",
                    name=lbl, legendgroup=grp,
                    showlegend=True,
                    line=dict(color=cb, width=1.5, dash="dot"),
                    hoverinfo="skip",
                ), row=1, col=1)

        elif t == "BB":
            has_visible = any(c != "none" for c in [cb, cu, cl])
            if has_visible:
                legend_c = style.get("color_legend") or _majority_color(cb, cu, cl)
                if not legend_c or legend_c == "none":
                    legend_c = next((c for c in [cb, cu, cl] if c != "none"), "#888888")
                # Anchor trace for legend entry (empty data)
                fig.add_trace(go.Scatter(
                    x=[None], y=[None], mode="lines",
                    name=lbl, legendgroup=grp, showlegend=True,
                    line=dict(color=legend_c, width=1.5),
                    hoverinfo="skip",
                ), row=1, col=1)
            if cu != "none":
                fig.add_trace(go.Scatter(
                    x=df.index, y=ci["upper"], mode="lines",
                    name=lbl, legendgroup=grp, showlegend=False,
                    line=dict(color=cu, width=1.0),
                    hoverinfo="skip",
                ), row=1, col=1)
            if cl != "none":
                fig.add_trace(go.Scatter(
                    x=df.index, y=ci["lower"], mode="lines",
                    name=lbl, legendgroup=grp, showlegend=False,
                    line=dict(color=cl, width=1.0),
                    hoverinfo="skip",
                ), row=1, col=1)
            if cb != "none":
                fig.add_trace(go.Scatter(
                    x=df.index, y=ci["mid"], mode="lines",
                    name=lbl, legendgroup=grp, showlegend=False,
                    line=dict(color=cb, width=1.0, dash="dot"),
                    hoverinfo="skip",
                ), row=1, col=1)

        elif t == "DC":
            has_visible = any(c != "none" for c in [cb, cu, cl])
            if has_visible:
                legend_c = style.get("color_legend") or _majority_color(cb, cu, cl)
                if not legend_c or legend_c == "none":
                    legend_c = next((c for c in [cb, cu, cl] if c != "none"), "#888888")
                # Anchor trace for legend entry (empty data)
                fig.add_trace(go.Scatter(
                    x=[None], y=[None], mode="lines",
                    name=lbl, legendgroup=grp, showlegend=True,
                    line=dict(color=legend_c, width=1.5),
                    hoverinfo="skip",
                ), row=1, col=1)
            if cu != "none":
                fig.add_trace(go.Scatter(
                    x=df.index, y=ci["upper"], mode="lines",
                    name=lbl, legendgroup=grp, showlegend=False,
                    line=dict(color=cu, width=1.2),
                    hoverinfo="skip",
                ), row=1, col=1)
            if cl != "none":
                fill_color = _hex_to_rgba(cl, 0.06)
                fill_kw = dict(fill="tonexty", fillcolor=fill_color) if cu != "none" else {}
                fig.add_trace(go.Scatter(
                    x=df.index, y=ci["lower"], mode="lines",
                    name=lbl, legendgroup=grp, showlegend=False,
                    line=dict(color=cl, width=1.2),
                    hoverinfo="skip", **fill_kw,
                ), row=1, col=1)
            if cb != "none":
                fig.add_trace(go.Scatter(
                    x=df.index, y=ci["mid"], mode="lines",
                    name=lbl, legendgroup=grp, showlegend=False,
                    line=dict(color=cb, width=0.8, dash="dash"),
                    hoverinfo="skip",
                ), row=1, col=1)

    # ── Fill-between traces ───────────────────────────────────────────
    for fb in (fill_betweens or []):
        c1_ref = fb.get("curve1")
        c2_ref = fb.get("curve2")
        color  = fb.get("color", "#ffffff")
        if not c1_ref or not c2_ref:
            continue
        y1 = _get_fb_curve(computed_inds, c1_ref)
        y2 = _get_fb_curve(computed_inds, c2_ref)
        if y1 is None or y2 is None:
            continue
        fill_color = _hex_to_rgba(color, 0.15)
        fig.add_trace(go.Scatter(
            x=df.index, y=y1, mode="lines",
            line=dict(color="rgba(0,0,0,0)", width=0),
            showlegend=False, hoverinfo="skip", name="",
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=y2, mode="lines",
            line=dict(color="rgba(0,0,0,0)", width=0),
            fill="tonexty", fillcolor=fill_color,
            showlegend=False, hoverinfo="skip", name="",
        ), row=1, col=1)

    # ── Candlestick ──────────────────────────────────────────────────
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["Open"], high=df["High"],
        low=df["Low"],   close=df["Close"],
        name=ticker,
        increasing=dict(line=dict(color=_C_UP,   width=1), fillcolor=_C_UP),
        decreasing=dict(line=dict(color=_C_DOWN, width=1), fillcolor=_C_DOWN),
        whiskerwidth=0.6,
        hoverinfo="skip",
    ), row=1, col=1)

    # ── Strategy signal markers ──────────────────────────────────────
    if signals is not None and len(signals) == len(df):
        buy_mask  = signals == 1
        sell_mask = signals == -1
        if buy_mask.any():
            fig.add_trace(go.Scatter(
                x=df.index[buy_mask],
                y=df["Low"][buy_mask] * (1 - _MARKER_OFFSET),
                mode="markers",
                marker=dict(
                    symbol="triangle-up", size=10, color=_C_STRAT_BUY,
                    line=dict(color=_C_STRAT_BUY, width=1),
                ),
                name="Buy",
                legendgroup="strategy-signals",
                showlegend=True,
                hovertemplate="<b>BUY</b><br>%{x}<extra></extra>",
            ), row=1, col=1)
        if sell_mask.any():
            fig.add_trace(go.Scatter(
                x=df.index[sell_mask],
                y=df["High"][sell_mask] * (1 + _MARKER_OFFSET),
                mode="markers",
                marker=dict(
                    symbol="triangle-down", size=10, color=_C_STRAT_SELL,
                    line=dict(color=_C_STRAT_SELL, width=1),
                ),
                name="Sell",
                legendgroup="strategy-signals",
                showlegend=True,
                hovertemplate="<b>SELL</b><br>%{x}<extra></extra>",
            ), row=1, col=1)

    # ── Volume subplot ───────────────────────────────────────────────
    if show_volume and vol_ind:
        vol_colors = [
            _C_UP if float(c_) >= float(o_) else _C_DOWN
            for c_, o_ in zip(df["Close"], df["Open"])
        ]
        fig.add_trace(go.Bar(
            x=df.index, y=vol_ind["volume"],
            name="Volume",
            marker=dict(color=vol_colors, line=dict(width=0)),
            opacity=0.65, showlegend=False, hoverinfo="skip",
        ), row=2, col=1)

        vol_ma_n    = vol_ind["params"].get("period", 20)
        vol_color   = vol_ind.get("style", {}).get("color_basis", vol_ind["color"])
        vol_lbl     = vol_ind["full_label"]
        if vol_color != "none":
            fig.add_trace(go.Scatter(
                x=df.index, y=vol_ind["vol_ma"], mode="lines",
                name=vol_lbl, legendgroup=vol_ind["id"], showlegend=True,
                line=dict(color=vol_color, width=1.5),
                hoverinfo="skip",
            ), row=2, col=1)

        # Volume hover probe
        vol_probe = []
        for i, (v_, vma_, o_, c_) in enumerate(
            zip(vol_ind["volume"], vol_ind["vol_ma"], df["Open"], df["Close"])
        ):
            v_, vma_ = float(v_), float(vma_)
            vp_  = vol_ind["vol_pct"][i]
            vz_  = vol_ind["vol_zscore"][i]
            up_  = float(c_) >= float(o_)
            vc_  = _C_UP if up_ else _C_DOWN
            arr_ = "▲" if up_ else "▼"
            ratio = v_ / vma_ if vma_ > 0 else 1.0
            sig  = ""
            if vp_ is not None and not math.isnan(vp_):
                sig += f"  <span style='color:#888888'>{_ordinal(round(vp_))} pct</span>"
            if vz_ is not None and not math.isnan(vz_):
                zs = "+" if vz_ >= 0 else ""
                sig += (f"  <span style='color:{_zscore_color(vz_)}'>"
                        f"{zs}{vz_:.1f}σ</span>")
            vol_probe.append([i, (
                f"<span style='color:{_AX}'>Vol </span>"
                f"<span style='color:{vc_}'>{arr_} {_fmt_vol(v_)}</span>  "
                f"<span style='color:#555555'>({ratio*100:.0f}% of avg)</span>"
                f"{sig}  "
                f"<span style='color:{_AX}'>MA({vol_ma_n}) </span>"
                f"<span style='color:{vol_color}'>{_fmt_vol(vma_)}</span>"
            )])

        fig.add_trace(go.Scatter(
            x=df.index, y=vol_ind["volume"], mode="lines",
            line=dict(color="rgba(0,0,0,0)", width=1),
            customdata=vol_probe,
            hovertemplate=(
                f"<b style='color:#ffffff'>{ticker}</b><br>%{{customdata[1]}}<extra></extra>"
            ),
            showlegend=False, name="",
        ), row=2, col=1)

    # ── Layout ──────────────────────────────────────────────────────
    fig.update_layout(
        paper_bgcolor=_BG, plot_bgcolor=_BG,
        font=dict(color=_AX, size=11,
                  family="'Inter', 'Segoe UI', system-ui, sans-serif"),
        title=dict(
            text=(f"<b>{ticker}</b>"
                  f"  <span style='color:{_AX};font-size:13px'>{interval_key}</span>"),
            font=dict(color="#ffffff", size=14),
            x=0.005, xanchor="left",
        ),
        legend=dict(
            bgcolor="rgba(17,17,17,0.85)", bordercolor=_GRID, borderwidth=1,
            font=dict(color="#cccccc", size=11),
            orientation="h", y=1.02, x=0, yanchor="bottom",
        ),
        margin=dict(l=10, r=70, t=46, b=36),
        hovermode="x unified", spikedistance=-1, hoverdistance=-1,
        hoverlabel=dict(
            bgcolor="#111111", bordercolor=_GRID,
            font=dict(color="#ffffff", size=11), namelength=-1,
        ),
    )

    if interval_key in _DAILY_PLUS:
        rb = [dict(bounds=["sat", "mon"])]
    elif interval_key in _INTRADAY_IVS:
        rb = [dict(bounds=["sat", "mon"]), dict(bounds=[16, 9.5], pattern="hour")]
    else:
        rb = []

    fig.update_xaxes(
        gridcolor=_GRID, linecolor=_GRID,
        tickfont=dict(color=_AX, size=10),
        rangeslider=dict(visible=False), rangebreaks=rb,
        showgrid=True, zeroline=False,
        showspikes=True, spikecolor="#555555",
        spikemode="across", spikethickness=1, spikedash="dot", spikesnap="cursor",
    )
    fig.update_yaxes(
        gridcolor=_GRID, linecolor=_GRID,
        tickfont=dict(color=_AX, size=10),
        side="right", showgrid=True, zeroline=False,
        row=1, col=1,
    )
    if show_volume:
        fig.update_yaxes(
            gridcolor=_GRID, linecolor=_GRID,
            tickfont=dict(color=_AX, size=9), tickformat=".2s",
            title_text="Vol", title_font=dict(color=_AX, size=9),
            side="right", showgrid=True, zeroline=False,
            row=2, col=1,
        )
    return fig


# ---------------------------------------------------------------------------
# Info card builders
# ---------------------------------------------------------------------------

_CARD_STYLE = {
    "backgroundColor": "#0f0f0f", "border": "1px solid #2a2a2a",
    "borderRadius": "6px", "padding": "8px 14px",
    "flex": "1", "minWidth": "220px",
}
_LBL        = {"color": "#555555", "fontSize": "0.72rem"}
_DATE_STYLE = {"color": "#888888", "fontSize": "0.72rem",
               "marginBottom": "5px", "letterSpacing": "0.04em"}
_IND_HDR    = {"color": "#888888", "fontSize": "0.78rem",
               "fontWeight": 600, "marginTop": "5px"}
_IND_VAL    = {"fontSize": "0.80rem"}
_IND_INDENT = {"paddingLeft": "10px", "marginTop": "1px"}


def _price_card(date_str, o, h, l, c,
                computed_inds: list[dict] | None = None,
                idx: int = 0) -> html.Div:
    up    = float(c) >= float(o)
    ccol  = _C_UP if up else _C_DOWN
    arrow = "▲" if up else "▼"
    rows: list = [
        html.Div(date_str, style=_DATE_STYLE),
        html.Div([
            html.Span("O ", style=_LBL),
            html.Span(f"{float(o):.2f}", style={"color": "#cccccc", "marginRight": "10px"}),
            html.Span("H ", style=_LBL),
            html.Span(f"{float(h):.2f}", style={"color": _C_UP, "marginRight": "10px"}),
            html.Span("L ", style=_LBL),
            html.Span(f"{float(l):.2f}", style={"color": _C_DOWN, "marginRight": "10px"}),
            html.Span("C ", style=_LBL),
            html.Span(f"{arrow} {float(c):.2f}", style={"color": ccol, "fontWeight": 700}),
        ], style={"fontSize": "0.86rem"}),
    ]

    for ci in (computed_inds or []):
        t     = ci["type"]
        style = ci.get("style", {})
        color = ci.get("color", "#888888")
        cb    = style.get("color_basis", color)
        cu    = style.get("color_upper", color)
        cl    = style.get("color_lower", color)
        lbl   = ci["full_label"]
        p     = ci["params"]

        if t == "SMA" and "values" in ci and idx < len(ci["values"]):
            v = ci["values"][idx]
            rows.append(html.Div([
                html.Span(f"{lbl} = ", style={"color": cb, "fontSize": "0.72rem"}),
                html.Span(f"{float(v):.4f}",
                          style={"color": "#cccccc", "fontSize": "0.82rem"}),
            ], style={"marginTop": "4px"}))

        elif t == "EMA" and "values" in ci and idx < len(ci["values"]):
            v = ci["values"][idx]
            rows.append(html.Div([
                html.Span(f"{lbl} = ", style={"color": cb, "fontSize": "0.72rem"}),
                html.Span(f"{float(v):.4f}",
                          style={"color": "#cccccc", "fontSize": "0.82rem"}),
            ], style={"marginTop": "4px"}))

        elif t == "BB" and "upper" in ci and idx < len(ci["upper"]):
            mid_v = ci["mid"][idx]; lo_v = ci["lower"][idx]; hi_v = ci["upper"][idx]
            rows.append(html.Div(lbl, style={**_IND_HDR, "color": cb}))
            rows.append(html.Div([
                html.Span("mid = ", style=_LBL),
                html.Span(f"{float(mid_v):.4f}",
                          style={"color": "#cccccc", **_IND_VAL, "marginRight": "10px"}),
                html.Span("lower = ", style=_LBL),
                html.Span(f"{float(lo_v):.4f}",
                          style={"color": "#cccccc", **_IND_VAL, "marginRight": "10px"}),
                html.Span("upper = ", style=_LBL),
                html.Span(f"{float(hi_v):.4f}",
                          style={"color": "#cccccc", **_IND_VAL}),
            ], style=_IND_INDENT))

        elif t == "DC" and "upper" in ci and idx < len(ci["upper"]):
            hi_v = ci["upper"][idx]; mid_v = ci["mid"][idx]; lo_v = ci["lower"][idx]
            rows.append(html.Div(lbl, style=_IND_HDR))
            rows.append(html.Div([
                html.Span("upper = ", style=_LBL),
                html.Span(f"{float(hi_v):.4f}",
                          style={"color": cu, **_IND_VAL, "marginRight": "10px"}),
                html.Span("mid = ", style=_LBL),
                html.Span(f"{float(mid_v):.4f}",
                          style={"color": cb, **_IND_VAL, "marginRight": "10px"}),
                html.Span("lower = ", style=_LBL),
                html.Span(f"{float(lo_v):.4f}",
                          style={"color": cl, **_IND_VAL}),
            ], style=_IND_INDENT))

    return html.Div(rows, style=_CARD_STYLE)


def _vol_card(v, vma, vol_ma_n, color="#4a90e2",
              vol_pct=None, vol_zscore=None) -> html.Div:
    if vma and vma > 0:
        ratio = v / vma
        vc    = _C_UP if ratio > 1.001 else (_C_DOWN if ratio < 0.999 else "#888888")
        arrow = "▲" if ratio > 1.001 else ("▼" if ratio < 0.999 else "—")
        pcts  = f"  ({ratio*100:.0f}% of avg)"
    else:
        vc, arrow, pcts = "#cccccc", "", ""

    sig: list = []
    if vol_pct is not None and not math.isnan(vol_pct):
        sig.append(html.Span(f"{_ordinal(round(vol_pct))} pct",
                             style={"color": "#777777", "fontSize": "0.75rem",
                                    "marginRight": "10px"}))
    if vol_zscore is not None and not math.isnan(vol_zscore):
        zs  = "+" if vol_zscore >= 0 else ""
        zcol = _zscore_color(vol_zscore)
        sig.append(html.Span(f"{zs}{vol_zscore:.2f}σ",
                             style={"color": zcol, "fontWeight": 700, "fontSize": "0.82rem"}))
        if abs(vol_zscore) >= 2.5:   lbl, lc = ("Extremely High" if vol_zscore > 0 else "Extremely Low"), zcol
        elif abs(vol_zscore) >= 1.5: lbl, lc = ("Very High" if vol_zscore > 0 else "Very Low"), zcol
        elif abs(vol_zscore) >= 0.5: lbl, lc = ("Above Avg" if vol_zscore > 0 else "Below Avg"), "#666666"
        else:                         lbl, lc = "Average", "#555555"
        sig.append(html.Span(f"  {lbl}", style={"color": lc, "fontSize": "0.74rem"}))

    rows: list = [
        html.Div("VOLUME", style=_DATE_STYLE),
        html.Div([
            html.Span(f"{arrow} {_fmt_vol(v)}" if arrow else _fmt_vol(v),
                      style={"color": vc, "fontWeight": 700, "fontSize": "0.86rem"}),
            html.Span(pcts, style={"color": "#555555", "fontSize": "0.75rem"}),
        ]),
    ]
    if sig:
        rows.append(html.Div(sig, style={"marginTop": "2px", "display": "flex",
                                         "alignItems": "baseline", "flexWrap": "wrap"}))
    if vma is not None:
        rows.append(html.Div([
            html.Span(f"MA({vol_ma_n}) ", style={"color": color, "fontSize": "0.72rem"}),
            html.Span(_fmt_vol(vma), style={"color": "#cccccc", "fontSize": "0.82rem"}),
        ], style={"marginTop": "3px"}))
    return html.Div(rows, style=_CARD_STYLE)


# ---------------------------------------------------------------------------
# Config form builder
# ---------------------------------------------------------------------------

_INPUT_STYLE = {
    "backgroundColor": "#0d0d0d", "color": "#cccccc",
    "border": "1px solid #2a2a2a",
}
_SELECT_STYLE = {
    "backgroundColor": "#0d0d0d", "color": "#cccccc",
    "border": "1px solid #2a2a2a",
}
_SEC_HDR = {
    "color": "#555555", "fontSize": "0.66rem", "fontWeight": 700,
    "letterSpacing": "0.10em", "marginBottom": "8px", "marginTop": "4px",
}


def _cfg_num(key, label, value, mn=None, mx=None, step=1):
    return dbc.Row([
        dbc.Label(label, width=5,
                  style={"color": "#aaaaaa", "fontSize": "0.84rem",
                         "display": "flex", "alignItems": "center"}),
        dbc.Col(dbc.Input(
            id={"type": "tech-cfg-input", "index": key},
            type="number", value=value, min=mn, max=mx, step=step, size="sm",
            style=_INPUT_STYLE,
        ), width=7),
    ], className="mb-2 align-items-center")


def _cfg_dd(key, label, value, options):
    """Param dropdown — uses dbc.Select (native <select>) for reliable dark-theme rendering."""
    return dbc.Row([
        dbc.Label(label, width=5,
                  style={"color": "#aaaaaa", "fontSize": "0.84rem",
                         "display": "flex", "alignItems": "center"}),
        dbc.Col(dbc.Select(
            id={"type": "tech-cfg-dropdown", "index": key},
            options=[{"label": o, "value": o} for o in options],
            value=value, size="sm",
            style=_SELECT_STYLE,
        ), width=7),
    ], className="mb-2 align-items-center")


def _cfg_color(key, label, value):
    """Color selector — uses dbc.Select with color palette options."""
    # Find a closest match or fallback
    valid = [c["value"] for c in _STYLE_COLORS]
    sel   = value if value in valid else (valid[0] if valid else "#f0c040")
    return dbc.Row([
        dbc.Label(label, width=5,
                  style={"color": "#aaaaaa", "fontSize": "0.84rem",
                         "display": "flex", "alignItems": "center"}),
        dbc.Col(
            html.Div([
                html.Span(
                    "■",
                    id={"type": "tech-cfg-color-swatch", "index": key},
                    style={"color": sel, "fontSize": "1.1rem",
                           "marginRight": "6px", "lineHeight": 1},
                ),
                dbc.Select(
                    id={"type": "tech-cfg-color", "index": key},
                    options=[{"label": c["label"], "value": c["value"]}
                             for c in _STYLE_COLORS],
                    value=sel, size="sm",
                    style={**_SELECT_STYLE, "flex": 1},
                ),
            ], style={"display": "flex", "alignItems": "center"}),
            width=7,
        ),
    ], className="mb-2 align-items-center")


def _cfg_legend_color(value: str) -> html.Div:
    """Separate legend-color picker (uses type tech-cfg-legend-color to avoid circular deps)."""
    valid = [c["value"] for c in _STYLE_COLORS if c["value"] != "none"]
    sel   = value if value in valid else (valid[0] if valid else "#f0c040")
    return html.Div([
        dbc.Row([
            dbc.Label("Legend Color", width=5,
                      style={"color": "#aaaaaa", "fontSize": "0.84rem",
                             "display": "flex", "alignItems": "center"}),
            dbc.Col(
                html.Div([
                    html.Span(
                        "■",
                        id={"type": "tech-cfg-legend-swatch", "index": 0},
                        style={"color": sel, "fontSize": "1.1rem",
                               "marginRight": "6px", "lineHeight": 1},
                    ),
                    dbc.Select(
                        id={"type": "tech-cfg-legend-color", "index": 0},
                        options=[{"label": c["label"], "value": c["value"]}
                                 for c in _STYLE_COLORS if c["value"] != "none"],
                        value=sel, size="sm",
                        style={**_SELECT_STYLE, "flex": 1},
                    ),
                ], style={"display": "flex", "alignItems": "center"}),
                width=7,
            ),
        ], className="mb-1 align-items-center"),
        html.Small(
            "Auto-set to majority color when others change. Set this last for a custom color.",
            style={"color": "#444444", "fontSize": "0.70rem", "paddingLeft": "2px",
                   "display": "block", "marginBottom": "6px"},
        ),
    ])


def _build_config_form(ind: dict) -> html.Div:
    t = ind["type"]
    p = ind["params"]
    s = ind.get("style", _default_style(ind.get("color", _IND_COLOR_POOL[0])))

    input_fields = []
    if t == "SMA":
        input_fields += [
            _cfg_num("period", "Length",  p.get("period", 50),  2, 500),
            _cfg_dd("source",  "Source",  p.get("source", "Close"), _SOURCES),
        ]
    elif t == "EMA":
        input_fields += [
            _cfg_num("period", "Length",  p.get("period", 21),  2, 500),
            _cfg_dd("source",  "Source",  p.get("source", "Close"), _SOURCES),
        ]
    elif t == "BB":
        input_fields += [
            _cfg_num("length",  "Length",       p.get("length", 20),   2,   500),
            _cfg_dd("ma_type",  "Basis MA Type", p.get("ma_type","SMA"), _MA_TYPES),
            _cfg_dd("source",   "Source",        p.get("source","Close"), _SOURCES),
            _cfg_num("stddev",  "StdDev",        p.get("stddev", 2.0),  0.1, 10.0, 0.1),
            _cfg_num("offset",  "Offset",        p.get("offset", 0),   -500, 500),
        ]
    elif t == "DC":
        input_fields += [_cfg_num("period", "Length", p.get("period", 20), 2, 200)]
    elif t == "VOLMA":
        input_fields += [_cfg_num("period", "Length", p.get("period", 20), 2, 500)]

    # Style fields (color per visual component)
    style_fields = []
    if t in ("SMA", "EMA", "VOLMA"):
        style_fields += [_cfg_color("color_basis", "Color", s.get("color_basis", ind["color"]))]
    elif t == "BB":
        style_fields += [
            _cfg_color("color_basis", "Basis (mid)", s.get("color_basis", ind["color"])),
            _cfg_color("color_upper", "Upper",       s.get("color_upper", ind["color"])),
            _cfg_color("color_lower", "Lower",       s.get("color_lower", ind["color"])),
        ]
    elif t == "DC":
        style_fields += [
            _cfg_color("color_basis", "Mid",   s.get("color_basis", ind["color"])),
            _cfg_color("color_upper", "Upper", s.get("color_upper", ind["color"])),
            _cfg_color("color_lower", "Lower", s.get("color_lower", ind["color"])),
        ]

    # Legend color: use stored value if present, else compute majority
    cb_v = s.get("color_basis", ind["color"])
    cu_v = s.get("color_upper", ind["color"])
    cl_v = s.get("color_lower", ind["color"])
    stored_legend = s.get("color_legend")
    valid_legend_values = [c["value"] for c in _STYLE_COLORS if c["value"] != "none"]
    if stored_legend and stored_legend in valid_legend_values:
        legend_val = stored_legend
    else:
        legend_val = _majority_color(cb_v, cu_v, cl_v, fallback=ind["color"])
        if legend_val == "none" or not legend_val:
            legend_val = ind["color"]
    style_fields += [
        html.Hr(style={"borderColor": "#1e1e1e", "margin": "8px 0"}),
        _cfg_legend_color(legend_val),
    ]

    return html.Div([
        html.Div("INPUTS", style=_SEC_HDR),
        dbc.Form(input_fields),
        html.Hr(style={"borderColor": "#2a2a2a", "margin": "10px 0"}),
        html.Div("STYLE", style=_SEC_HDR),
        dbc.Form(style_fields),
    ], style={"padding": "2px 0"})


# ---------------------------------------------------------------------------
# Indicator chip renderer
# ---------------------------------------------------------------------------

def _render_chips(indicators: list[dict]) -> list:
    chips = []
    for ind in indicators:
        style  = ind.get("style", _default_style(ind.get("color", "#888888")))
        color  = style.get("color_legend") or style.get("color_basis", ind.get("color", "#888888"))
        if not color or color == "none":
            color = style.get("color_basis", ind.get("color", "#888888"))
        if not color or color == "none":
            color = "#888888"
        label  = _ind_full_label(ind)
        ind_id = ind["id"]
        chips.append(html.Div([
            html.Span("●", style={"color": color, "fontSize": "0.85rem",
                                  "marginRight": "5px", "lineHeight": 1}),
            html.Span(label, style={"color": "#cccccc", "fontSize": "0.80rem",
                                    "marginRight": "6px"}),
            html.Span(
                html.I(className="bi-gear-fill"),
                id={"type": "tech-ind-gear", "index": ind_id},
                n_clicks=0,
                style={"color": "#555555", "fontSize": "0.76rem",
                       "cursor": "pointer", "marginRight": "4px"},
                title="Configure",
            ),
            html.Span(
                html.I(className="bi-x-lg"),
                id={"type": "tech-ind-remove", "index": ind_id},
                n_clicks=0,
                style={"color": "#444444", "fontSize": "0.74rem", "cursor": "pointer"},
                title="Remove",
            ),
        ], style={
            "display": "inline-flex", "alignItems": "center",
            "backgroundColor": "#111111", "border": "1px solid #2a2a2a",
            "borderRadius": "4px", "padding": "3px 8px",
            "marginRight": "4px", "marginBottom": "2px",
        }))
    return chips


# ---------------------------------------------------------------------------
# Fill-between helpers (imported from frontend.strategy.data)
# ---------------------------------------------------------------------------
# _get_fb_curve is imported at the top of this file.


def _fill_curve_options(indicators: list[dict]) -> list[dict]:
    opts = []
    for ind in indicators:
        t = ind["type"]
        if t == "VOLMA":
            continue
        ind_id = ind["id"]
        lbl = _ind_full_label(ind)
        if t in ("SMA", "EMA"):
            opts.append({"label": lbl, "value": f"{ind_id}:values"})
        elif t in ("BB", "DC"):
            opts.append({"label": f"{lbl} Upper", "value": f"{ind_id}:upper"})
            opts.append({"label": f"{lbl} Mid",   "value": f"{ind_id}:mid"})
            opts.append({"label": f"{lbl} Lower",  "value": f"{ind_id}:lower"})
    return opts


def _build_fb_modal_body(fill_betweens: list[dict], ind_options: list[dict]) -> html.Div:
    if not ind_options:
        return html.Div("No indicators available. Add price indicators first.",
                        style={"color": "#666666", "fontSize": "0.84rem", "padding": "10px"})

    opt_vals = [o["value"] for o in ind_options]
    rows = []
    for fb in fill_betweens:
        fb_id = fb["id"]
        c1    = fb.get("curve1", "")
        c2    = fb.get("curve2", "")
        color = fb.get("color", "#ffffff")
        if c1 not in opt_vals:
            c1 = opt_vals[0]
        if c2 not in opt_vals:
            c2 = opt_vals[0]
        valid_color = color if color in _STYLE_COLOR_VALUES else _STYLE_COLOR_VALUES[0]

        rows.append(dbc.Row([
            dbc.Col(dbc.Select(
                id={"type": "tech-fb-curve1", "index": fb_id},
                options=ind_options, value=c1, size="sm",
                style=_SELECT_STYLE,
            ), width=4),
            dbc.Col(dbc.Select(
                id={"type": "tech-fb-curve2", "index": fb_id},
                options=ind_options, value=c2, size="sm",
                style=_SELECT_STYLE,
            ), width=4),
            dbc.Col(
                html.Div([
                    html.Span(
                        "■",
                        id={"type": "tech-fb-color-swatch", "index": fb_id},
                        style={"color": valid_color, "fontSize": "1.1rem",
                               "marginRight": "4px", "lineHeight": 1},
                    ),
                    dbc.Select(
                        id={"type": "tech-fb-color", "index": fb_id},
                        options=[{"label": c["label"], "value": c["value"]}
                                 for c in _STYLE_COLORS],
                        value=valid_color, size="sm",
                        style={**_SELECT_STYLE, "flex": 1},
                    ),
                ], style={"display": "flex", "alignItems": "center"}),
                width=3,
            ),
            dbc.Col(
                html.Span(
                    html.I(className="bi-x-lg"),
                    id={"type": "tech-fb-remove", "index": fb_id},
                    n_clicks=0,
                    style={"color": "#888888", "cursor": "pointer", "fontSize": "0.86rem"},
                    title="Remove",
                ),
                width=1, style={"display": "flex", "alignItems": "center",
                                "justifyContent": "center"},
            ),
        ], className="mb-2 g-1 align-items-center"))

    if not rows:
        rows = [html.Div("No fill-between configurations yet.",
                         style={"color": "#555555", "fontSize": "0.80rem",
                                "marginBottom": "10px"})]

    headers = dbc.Row([
        dbc.Col(html.Span("Plot 1", style={"color": "#666666", "fontSize": "0.70rem"}), width=4),
        dbc.Col(html.Span("Plot 2", style={"color": "#666666", "fontSize": "0.70rem"}), width=4),
        dbc.Col(html.Span("Color",  style={"color": "#666666", "fontSize": "0.70rem"}), width=3),
        dbc.Col(width=1),
    ], className="mb-1")

    return html.Div([headers, *rows])


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------

def _iv_btn(label: str, value: str) -> dbc.Button:
    return dbc.Button(
        label,
        id={"type": "tech-iv-btn", "index": value},
        size="sm", color="primary",
        outline=(value != _DEFAULT_IV),
        className="preset-btn", n_clicks=0,
        style={"minWidth": "36px", "padding": "3px 8px", "fontSize": "0.78rem"},
    )


_MODAL_HDR = {"backgroundColor": "#111111", "borderBottom": "1px solid #2a2a2a"}
_MODAL_FTR = {"backgroundColor": "#111111", "borderTop":    "1px solid #2a2a2a"}
_MODAL_BDY = {"backgroundColor": "#0d0d0d"}


# ---------------------------------------------------------------------------
# Strategy helpers
# ---------------------------------------------------------------------------

def _strategy_dropdown_options() -> list[dict]:
    """Build dropdown options from all available strategies."""
    options = []
    for s in list_strategies():
        prefix = "[built-in] " if s["is_builtin"] else ""
        options.append({"label": prefix + s["display_name"], "value": s["name"]})
    return options


def _build_strategy_param_form(params_spec: dict) -> list:
    """Auto-generate parameter form fields from a strategy PARAMS dict."""
    _num_style = {
        "width": "75px", "backgroundColor": "#111111",
        "color": "#ffffff", "border": "1px solid #2a2a2a",
        "fontSize": "0.78rem",
    }
    _lbl_style = {
        "color": "#888888", "fontSize": "0.72rem",
        "marginRight": "4px", "whiteSpace": "nowrap",
    }
    _dd_style = {"fontSize": "0.78rem", "minWidth": "100px"}
    items = []
    for key, spec in params_spec.items():
        ptype = spec.get("type", "int")
        label = spec.get("desc", key)
        default = spec.get("default")
        wrap = {"display": "flex", "alignItems": "center", "gap": "3px"}
        if ptype in ("int", "float"):
            step = 1 if ptype == "int" else 0.1
            items.append(html.Div([
                html.Span(f"{label}:", style=_lbl_style),
                dbc.Input(
                    id={"type": "tech-strat-num", "index": key},
                    type="number", value=default,
                    min=spec.get("min"), max=spec.get("max"), step=step,
                    size="sm", style=_num_style,
                ),
            ], style=wrap))
        elif ptype == "choice":
            options = [{"label": o, "value": o} for o in spec.get("options", [])]
            items.append(html.Div([
                html.Span(f"{label}:", style=_lbl_style),
                dcc.Dropdown(
                    id={"type": "tech-strat-dd", "index": key},
                    options=options, value=default, clearable=False,
                    style=_dd_style,
                ),
            ], style=wrap))
    return items


def _build_perf_card(display_name: str, perf: dict) -> html.Div:
    """Render a two-row performance summary below the chart."""
    trade_count = perf.get("trade_count", 0)
    if trade_count == 0:
        return html.Div(
            f"Strategy '{display_name}' — no trades generated on this data.",
            style={"color": "#555555", "fontSize": "0.72rem", "marginTop": "4px"},
        )

    total_pnl           = perf["total_pnl"]
    avg_pnl             = perf["avg_pnl"]
    win_rate            = perf["win_rate"] * 100
    strategy_return_pct = perf.get("strategy_return_pct", 0.0)
    avg_return_pct      = perf.get("avg_return_pct", 0.0)
    spy_return_pct      = perf.get("spy_return_pct")
    beat_spy            = perf.get("beat_spy")
    data_start          = perf.get("data_start_date", "")
    data_end            = perf.get("data_end_date", "")
    bar_count           = perf.get("bar_count", 0)

    pnl_color   = _C_STRAT_BUY if total_pnl           >= 0 else _C_STRAT_SELL
    ret_color   = _C_STRAT_BUY if strategy_return_pct >= 0 else _C_STRAT_SELL
    sign_total  = "+" if total_pnl           >= 0 else ""
    sign_avg    = "+" if avg_pnl             >= 0 else ""
    sign_ret    = "+" if strategy_return_pct >= 0 else ""
    sign_avgret = "+" if avg_return_pct      >= 0 else ""

    sep = html.Span("  ·  ", style={"color": "#333333"})

    row1 = html.Div([
        html.Span(f"Strategy: {display_name}",
                  style={"color": "#888888", "fontSize": "0.72rem"}),
        sep,
        html.Span(f"{trade_count} trades",
                  style={"color": "#aaaaaa", "fontSize": "0.72rem"}),
        sep,
        html.Span(f"Win rate: {win_rate:.1f}%",
                  style={"color": "#aaaaaa", "fontSize": "0.72rem"}),
        sep,
        html.Span(f"Total P&L: {sign_total}{total_pnl:.2f}",
                  style={"color": pnl_color, "fontSize": "0.72rem"}),
        sep,
        html.Span(f"Avg/trade: {sign_avg}{avg_pnl:.2f}",
                  style={"color": "#aaaaaa", "fontSize": "0.72rem"}),
    ])

    # Row 2: return metrics, SPY comparison, date range
    row2_items = [
        html.Span(f"Return: {sign_ret}{strategy_return_pct:.2f}%",
                  style={"color": ret_color, "fontSize": "0.72rem"}),
        sep,
        html.Span(f"Avg/trade: {sign_avgret}{avg_return_pct:.2f}%",
                  style={"color": "#aaaaaa", "fontSize": "0.72rem"}),
    ]
    if spy_return_pct is not None:
        spy_color  = _C_STRAT_BUY if spy_return_pct >= 0 else _C_STRAT_SELL
        sign_spy   = "+" if spy_return_pct >= 0 else ""
        beat_label = "✓ beat SPY" if beat_spy else "✗ missed SPY"
        beat_color = _C_STRAT_BUY if beat_spy else _C_STRAT_SELL
        row2_items += [
            sep,
            html.Span(f"SPY: {sign_spy}{spy_return_pct:.2f}%",
                      style={"color": spy_color, "fontSize": "0.72rem"}),
            sep,
            html.Span(beat_label,
                      style={"color": beat_color, "fontSize": "0.72rem",
                             "fontWeight": 600}),
        ]
    if data_start and data_end:
        row2_items += [
            sep,
            html.Span(f"{data_start} → {data_end} ({bar_count} bars)",
                      style={"color": "#555555", "fontSize": "0.72rem"}),
        ]
    row2 = html.Div(row2_items, style={"marginTop": "2px"})

    return html.Div([row1, row2], style={"marginTop": "4px"})

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

layout = html.Div([
    html.Div([
        html.Span("Technical ", className="page-title"),
        html.Span("Analysis",   className="page-title title-accent"),
    ], style={"marginBottom": "14px"}),

    dcc.Store(id="tech-active-interval",    data=_DEFAULT_IV),
    dcc.Store(id="tech-chart-data"),
    dcc.Store(id="tech-indicators-store",   data=_DEFAULT_INDICATORS),
    dcc.Store(id="tech-config-ind-id",      data=None),
    dcc.Store(id="tech-fill-between-store", data=[]),
    dcc.Store(id="tech-strategy-store",     data=None),
    dcc.Download(id="tech-preset-download"),

    # ── Ticker + interval row ─────────────────────────────────────────
    dbc.Row([
        dbc.Col(
            dbc.InputGroup([
                dbc.InputGroupText(
                    html.I(className="bi-graph-up"),
                    style={"backgroundColor": "#1a1a1a", "border": "1px solid #2a2a2a",
                           "color": "#888888"},
                ),
                dbc.Input(
                    id="tech-ticker", placeholder="Ticker  e.g. AAPL",
                    value="AAPL", debounce=True, size="sm",
                    style={"backgroundColor": "#111111", "color": "#ffffff",
                           "border": "1px solid #2a2a2a", "borderLeft": "none",
                           "fontWeight": 600, "textTransform": "uppercase",
                           "letterSpacing": "0.04em"},
                ),
            ]),
            md=3,
        ),
        dbc.Col(
            html.Div([_iv_btn(lbl, val) for lbl, val in _INTERVALS],
                     style={"display": "flex", "gap": "3px", "flexWrap": "wrap"}),
            md=7, style={"display": "flex", "alignItems": "center"},
        ),
        dbc.Col(
            dbc.Button(
                [html.I(className="bi-arrow-clockwise me-1"), "Load"],
                id="tech-load-btn", color="secondary", size="sm", outline=True,
            ),
            md=2, style={"textAlign": "right"},
        ),
    ], className="mb-2 g-2 align-items-center"),

    # ── Indicator bar ─────────────────────────────────────────────────
    html.Div([
        html.Span(
            "INDICATORS",
            style={"color": "#444444", "fontSize": "0.66rem", "fontWeight": 700,
                   "letterSpacing": "0.12em", "flexShrink": 0,
                   "marginRight": "10px", "alignSelf": "center"},
        ),
        html.Div([
            html.Div(
                id="tech-indicator-chips",
                style={"display": "flex", "flexWrap": "wrap",
                       "alignItems": "center", "gap": "2px"},
            ),
            html.Span(
                "Click an indicator chip to configure its parameters.",
                style={"color": "#444444", "fontSize": "0.65rem", "marginLeft": "6px",
                       "alignSelf": "center", "whiteSpace": "nowrap"},
            ),
        ], style={"display": "flex", "flex": "1", "alignItems": "center",
                  "flexWrap": "wrap", "gap": "2px"}),
        dbc.Button(
            [html.I(className="bi-plus-lg me-1"), "Add Indicator"],
            id="tech-add-ind-btn",
            size="sm", color="secondary", outline=True,
            style={"fontSize": "0.76rem", "flexShrink": 0, "padding": "3px 10px"},
        ),
        dbc.Button(
            [html.I(className="bi-layers me-1"), "Fill Between"],
            id="tech-fill-between-open-btn",
            size="sm", color="secondary", outline=True,
            style={"fontSize": "0.76rem", "flexShrink": 0, "padding": "3px 10px"},
        ),
        dbc.Button(
            [html.I(className="bi-download me-1"), "Export"],
            id="tech-save-preset-btn",
            size="sm", color="secondary", outline=True,
            style={"fontSize": "0.76rem", "flexShrink": 0, "padding": "3px 10px"},
        ),
    ], style={
        "display": "flex", "alignItems": "center",
        "padding": "7px 14px", "marginBottom": "10px",
        "backgroundColor": "#0a0a0a", "border": "1px solid #1e1e1e",
        "borderRadius": "4px", "flexWrap": "wrap", "gap": "6px", "rowGap": "6px",
    }),

    # ── Preset Library Bar ─────────────────────────────────────────────
    html.Div([
        html.Span("PRESETS", style={
            "color": "#444444", "fontSize": "0.66rem", "fontWeight": 700,
            "letterSpacing": "0.12em", "flexShrink": 0, "marginRight": "10px",
            "alignSelf": "center",
        }),
        html.Div(id="tech-preset-status",
                 style={"fontSize": "0.70rem", "minHeight": "18px",
                        "flexShrink": 0, "marginRight": "8px",
                        "alignSelf": "center"}),
        dbc.InputGroup([
            dbc.Input(
                id="tech-preset-name-input",
                placeholder="Preset name…",
                size="sm",
                style={"backgroundColor": "#111111", "color": "#ffffff",
                       "border": "1px solid #2a2a2a", "fontSize": "0.78rem",
                       "maxWidth": "180px"},
            ),
            dbc.Button("Save", id="tech-preset-save-btn",
                       color="success", outline=True, size="sm", n_clicks=0,
                       style={"fontSize": "0.76rem", "padding": "3px 10px"}),
        ], size="sm", style={"flexShrink": 0, "width": "auto", "marginRight": "12px"}),
        html.Div([
            dcc.Dropdown(
                id="tech-preset-select",
                placeholder="Load a preset…",
                options=_preset_dropdown_options(),
                style={"fontSize": "0.78rem", "minWidth": "200px"},
                clearable=True,
            ),
        ], style={"flexShrink": 0, "marginRight": "6px"}),
        dbc.Button("Load", id="tech-preset-load-btn",
                   color="primary", outline=True, size="sm", n_clicks=0,
                   style={"fontSize": "0.76rem", "padding": "3px 10px",
                          "flexShrink": 0}),
        dbc.Button("Delete", id="tech-preset-delete-btn",
                   color="danger", outline=True, size="sm", n_clicks=0,
                   style={"fontSize": "0.76rem", "padding": "3px 10px",
                          "flexShrink": 0, "marginLeft": "4px"}),
    ], style={
        "display": "flex", "alignItems": "center",
        "padding": "7px 14px", "marginBottom": "10px",
        "backgroundColor": "#0a0a0a", "border": "1px solid #1e1e1e",
        "borderRadius": "4px", "flexWrap": "wrap", "gap": "6px", "rowGap": "6px",
    }),

    # ── Strategy Bar ──────────────────────────────────────────────────
    html.Div([
        html.Span(
            "STRATEGY",
            style={"color": "#444444", "fontSize": "0.66rem", "fontWeight": 700,
                   "letterSpacing": "0.12em", "flexShrink": 0,
                   "marginRight": "10px", "alignSelf": "center"},
        ),
        dcc.Dropdown(
            id="tech-strategy-select",
            placeholder="Select a strategy…",
            options=_strategy_dropdown_options(),
            clearable=True,
            style={"fontSize": "0.78rem", "minWidth": "220px", "flexShrink": 0},
        ),
        html.Div(
            id="tech-strategy-param-panel",
            style={"display": "flex", "flex": "1", "alignItems": "center",
                   "flexWrap": "wrap", "gap": "8px", "marginLeft": "10px"},
        ),
        dbc.Button(
            [html.I(className="bi-play-fill me-1"), "Run"],
            id="tech-strategy-run-btn",
            size="sm", color="success", outline=True, n_clicks=0,
            style={"fontSize": "0.76rem", "flexShrink": 0, "padding": "3px 10px"},
        ),
        dbc.Button(
            [html.I(className="bi-x-lg me-1"), "Clear"],
            id="tech-strategy-clear-btn",
            size="sm", color="secondary", outline=True, n_clicks=0,
            style={"fontSize": "0.76rem", "flexShrink": 0, "padding": "3px 10px"},
        ),
        dbc.Button(
            [html.I(className="bi-arrow-clockwise me-1"), "Reload"],
            id="tech-strategy-reload-btn",
            size="sm", color="secondary", outline=True, n_clicks=0,
            style={"fontSize": "0.76rem", "flexShrink": 0, "padding": "3px 10px"},
        ),
        dbc.Button(
            [html.I(className="bi-plus-lg me-1"), "New"],
            id="tech-strategy-new-btn",
            size="sm", color="secondary", outline=True, n_clicks=0,
            style={"fontSize": "0.76rem", "flexShrink": 0, "padding": "3px 10px"},
        ),
    ], style={
        "display": "flex", "alignItems": "center",
        "padding": "7px 14px", "marginBottom": "10px",
        "backgroundColor": "#0a0a0a", "border": "1px solid #1e1e1e",
        "borderRadius": "4px", "flexWrap": "wrap", "gap": "6px", "rowGap": "6px",
    }),

    # ── New Strategy Modal ────────────────────────────────────────────
    dbc.Modal([
        dbc.ModalHeader(
            dbc.ModalTitle("New Strategy",
                           style={"color": "#ffffff", "fontSize": "1rem"}),
            style=_MODAL_HDR, close_button=True,
        ),
        dbc.ModalBody(
            html.Div([
                html.Div("Strategy name:",
                         style={"color": "#888888", "fontSize": "0.80rem",
                                "marginBottom": "4px"}),
                dbc.Input(
                    id="tech-strategy-new-name",
                    placeholder="e.g. My Strategy",
                    size="sm",
                    style={"backgroundColor": "#111111", "color": "#ffffff",
                           "border": "1px solid #2a2a2a", "marginBottom": "8px"},
                ),
                html.Div(id="tech-strategy-new-path",
                         style={"fontSize": "0.74rem", "color": "#666666"}),
            ]),
            style=_MODAL_BDY,
        ),
        dbc.ModalFooter([
            dbc.Button("Create", id="tech-strategy-create-btn",
                       color="success", size="sm"),
            dbc.Button("Cancel", id="tech-strategy-new-cancel-btn",
                       color="secondary", outline=True, size="sm",
                       style={"marginLeft": "8px"}),
        ], style=_MODAL_FTR),
    ], id="tech-strategy-new-modal", is_open=False, centered=True,
       backdrop=True, style={"maxWidth": "420px"}),

    # ── Add Indicator Modal ───────────────────────────────────────────
    dbc.Modal([
        dbc.ModalHeader(
            dbc.ModalTitle("Add Indicator",
                           style={"color": "#ffffff", "fontSize": "1rem"}),
            style=_MODAL_HDR, close_button=True,
        ),
        dbc.ModalBody(
            html.Div([
                dbc.Button(
                    [
                        html.Div(info["label"],
                                 style={"fontWeight": 700, "color": "#cccccc",
                                        "fontSize": "0.86rem"}),
                        html.Div(info["desc"],
                                 style={"color": "#666666", "fontSize": "0.74rem",
                                        "marginTop": "2px"}),
                    ],
                    id={"type": "tech-add-ind-type", "index": ind_type},
                    color="dark", outline=True, n_clicks=0,
                    style={
                        "textAlign": "left", "width": "100%",
                        "backgroundColor": "#0a0a0a",
                        "border": "1px solid #2a2a2a",
                        "borderRadius": "6px", "padding": "10px 14px",
                        "marginBottom": "6px",
                    },
                )
                for ind_type, info in _IND_TYPES.items()
            ]),
            style=_MODAL_BDY,
        ),
    ], id="tech-add-modal", is_open=False, centered=True,
       backdrop=True, class_name="tech-add-modal-dialog"),

    # ── Config Modal ──────────────────────────────────────────────────
    dbc.Modal([
        dbc.ModalHeader(
            dbc.ModalTitle(id="tech-config-modal-title",
                           style={"color": "#ffffff", "fontSize": "1rem"}),
            style=_MODAL_HDR, close_button=True,
        ),
        dbc.ModalBody(
            html.Div(id="tech-config-modal-body"),
            style=_MODAL_BDY,
        ),
        dbc.ModalFooter([
            dbc.Button("Save",   id="tech-config-save-btn",
                       color="primary", size="sm"),
            dbc.Button("Cancel", id="tech-config-cancel-btn",
                       color="secondary", outline=True, size="sm",
                       style={"marginLeft": "8px"}),
        ], style=_MODAL_FTR),
    ], id="tech-config-modal", is_open=False, centered=True,
       backdrop=True, class_name="tech-config-modal-dialog"),

    # ── Fill Between Modal ────────────────────────────────────────────
    dbc.Modal([
        dbc.ModalHeader(
            dbc.ModalTitle("Fill Between",
                           style={"color": "#ffffff", "fontSize": "1rem"}),
            style=_MODAL_HDR, close_button=True,
        ),
        dbc.ModalBody(
            html.Div([
                html.Div(id="tech-fill-between-modal-body"),
                dbc.Button(
                    [html.I(className="bi-plus-lg me-1"), "Add Fill Between"],
                    id="tech-fill-between-add-btn",
                    size="sm", color="secondary", outline=True, n_clicks=0,
                    style={"fontSize": "0.76rem", "marginTop": "6px"},
                ),
            ]),
            style=_MODAL_BDY,
        ),
        dbc.ModalFooter([
            dbc.Button("Save",  id="tech-fill-between-save-btn",
                       color="primary", size="sm"),
            dbc.Button("Close", id="tech-fill-between-close-btn",
                       color="secondary", outline=True, size="sm",
                       style={"marginLeft": "8px"}),
        ], style=_MODAL_FTR),
    ], id="tech-fill-between-modal", is_open=False, centered=True,
       backdrop=True, style={"maxWidth": "560px"}),

    # ── Save Preset Modal ─────────────────────────────────────────────
    dbc.Modal([
        dbc.ModalHeader(
            dbc.ModalTitle("Export Indicator Preset",
                           style={"color": "#ffffff", "fontSize": "1rem"}),
            style=_MODAL_HDR, close_button=True,
        ),
        dbc.ModalBody(
            html.Div(id="tech-save-preset-modal-body"),
            style=_MODAL_BDY,
        ),
        dbc.ModalFooter([
            dbc.Button("Download", id="tech-save-preset-download-btn",
                       color="primary", size="sm"),
            dbc.Button("Cancel", id="tech-save-preset-cancel-btn",
                       color="secondary", outline=True, size="sm",
                       style={"marginLeft": "8px"}),
        ], style=_MODAL_FTR),
    ], id="tech-save-preset-modal", is_open=False, centered=True,
       backdrop=True, style={"maxWidth": "480px"}),

    # ── Chart ─────────────────────────────────────────────────────────
    dcc.Loading(
        dcc.Graph(
            id="tech-chart",
            config={
                "displayModeBar": True, "scrollZoom": True,
                "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d"],
                "displaylogo": False,
                "toImageButtonOptions": {"format": "png", "scale": 2},
            },
            style={"height": "74vh", "backgroundColor": _BG},
        ),
        type="circle", color="#4a90e2",
    ),

    # ── Hover info cards ──────────────────────────────────────────────
    html.Div(
        id="tech-hover-info",
        style={"display": "flex", "gap": "8px", "flexWrap": "wrap",
               "marginTop": "8px", "minHeight": "70px"},
    ),
    html.Div(id="tech-strategy-perf-card"),
    html.Div(
        id="tech-status",
        style={"marginTop": "4px", "fontSize": "0.72rem", "color": "#444444"},
    ),
])


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

@callback(
    Output("tech-active-interval", "data"),
    [Input({"type": "tech-iv-btn", "index": iv[1]}, "n_clicks") for iv in _INTERVALS],
    prevent_initial_call=True,
)
def _set_interval(*_):
    triggered = ctx.triggered_id
    if isinstance(triggered, dict):
        return triggered.get("index", _DEFAULT_IV)
    return _DEFAULT_IV


@callback(
    [Output({"type": "tech-iv-btn", "index": iv[1]}, "outline") for iv in _INTERVALS],
    Input("tech-active-interval", "data"),
)
def _highlight_iv(active: str):
    active = active or _DEFAULT_IV
    return [iv[1] != active for iv in _INTERVALS]


@callback(
    Output("tech-add-modal", "is_open"),
    Input("tech-add-ind-btn", "n_clicks"),
    prevent_initial_call=True,
)
def _open_add_modal(n):
    return bool(n)


@callback(
    Output("tech-indicators-store",   "data"),
    Output("tech-add-modal",          "is_open", allow_duplicate=True),
    Output("tech-config-modal",       "is_open", allow_duplicate=True),
    Output("tech-config-modal-title", "children", allow_duplicate=True),
    Output("tech-config-modal-body",  "children", allow_duplicate=True),
    Output("tech-config-ind-id",      "data",     allow_duplicate=True),
    Input({"type": "tech-add-ind-type", "index": ALL}, "n_clicks"),
    State("tech-indicators-store", "data"),
    prevent_initial_call=True,
)
def _add_indicator(clicks, indicators):
    if not any(clicks):
        return no_update, no_update, no_update, no_update, no_update, no_update
    triggered = ctx.triggered_id
    if not triggered or not isinstance(triggered, dict):
        return no_update, no_update, no_update, no_update, no_update, no_update
    ind_type   = triggered["index"]
    indicators = list(indicators or [])
    used       = {ind["color"] for ind in indicators}
    if ind_type == "VOLMA":
        color = "#4a90e2"
    else:
        color = next(
            (c for c in _IND_COLOR_POOL if c not in used),
            _IND_COLOR_POOL[len(indicators) % len(_IND_COLOR_POOL)],
        )
    new_ind = {
        "id":     f"{ind_type.lower()}-{int(time.time() * 1000)}",
        "type":   ind_type,
        "color":  color,
        "params": dict(_IND_DEFAULTS[ind_type]),
        "style":  _default_style(color),
    }
    type_label = _IND_TYPES.get(ind_type, {}).get("label", ind_type)
    return (
        indicators + [new_ind],
        False,                          # close Add modal
        True,                           # open Config modal immediately
        f"Configure {type_label}",
        _build_config_form(new_ind),
        new_ind["id"],
    )


@callback(
    Output("tech-indicators-store", "data", allow_duplicate=True),
    Input({"type": "tech-ind-remove", "index": ALL}, "n_clicks"),
    State("tech-indicators-store", "data"),
    prevent_initial_call=True,
)
def _remove_indicator(clicks, indicators):
    if not any(clicks):
        return no_update
    triggered = ctx.triggered_id
    if not triggered or not isinstance(triggered, dict):
        return no_update
    ind_id = triggered["index"]
    return [ind for ind in (indicators or []) if ind["id"] != ind_id]


@callback(
    Output("tech-indicator-chips", "children"),
    Input("tech-indicators-store", "data"),
)
def _render_indicator_chips(indicators):
    return _render_chips(indicators or [])


@callback(
    Output("tech-config-modal",       "is_open"),
    Output("tech-config-modal-title", "children"),
    Output("tech-config-modal-body",  "children"),
    Output("tech-config-ind-id",      "data"),
    Input({"type": "tech-ind-gear", "index": ALL}, "n_clicks"),
    State("tech-indicators-store", "data"),
    prevent_initial_call=True,
)
def _open_config_modal(gear_clicks, indicators):
    if not any(gear_clicks):
        return no_update, no_update, no_update, no_update
    triggered = ctx.triggered_id
    if not triggered or not isinstance(triggered, dict):
        return no_update, no_update, no_update, no_update
    ind_id = triggered["index"]
    ind    = next((i for i in (indicators or []) if i["id"] == ind_id), None)
    if not ind:
        return no_update, no_update, no_update, no_update
    type_label = _IND_TYPES.get(ind["type"], {}).get("label", ind["type"])
    return True, f"Configure {type_label}", _build_config_form(ind), ind_id


@callback(
    Output("tech-indicators-store", "data",    allow_duplicate=True),
    Output("tech-config-modal",     "is_open", allow_duplicate=True),
    Input("tech-config-save-btn",  "n_clicks"),
    State("tech-config-ind-id",    "data"),
    State("tech-indicators-store", "data"),
    State({"type": "tech-cfg-input",        "index": ALL}, "value"),
    State({"type": "tech-cfg-input",        "index": ALL}, "id"),
    State({"type": "tech-cfg-dropdown",     "index": ALL}, "value"),
    State({"type": "tech-cfg-dropdown",     "index": ALL}, "id"),
    State({"type": "tech-cfg-color",        "index": ALL}, "value"),
    State({"type": "tech-cfg-color",        "index": ALL}, "id"),
    State({"type": "tech-cfg-legend-color", "index": ALL}, "value"),
    prevent_initial_call=True,
)
def _save_config(n, ind_id, indicators,
                 num_vals, num_ids, dd_vals, dd_ids,
                 color_vals, color_ids, legend_color_vals):
    if not n or not ind_id:
        return no_update, no_update
    params = {}
    for val, id_dict in zip(num_vals, num_ids):
        if val is not None:
            params[id_dict["index"]] = val
    for val, id_dict in zip(dd_vals, dd_ids):
        if val is not None:
            params[id_dict["index"]] = val
    style = {}
    for val, id_dict in zip(color_vals, color_ids):
        if val is not None:
            style[id_dict["index"]] = val
    # Capture legend color from its separate picker type
    for val in (legend_color_vals or []):
        if val is not None:
            style["color_legend"] = val

    updated = []
    for ind in (indicators or []):
        if ind["id"] == ind_id:
            new_color = style.get("color_basis", ind.get("color", _IND_COLOR_POOL[0]))
            ind = {**ind, "params": params, "style": style, "color": new_color}
        updated.append(ind)
    return updated, False


@callback(
    Output("tech-config-modal", "is_open", allow_duplicate=True),
    Input("tech-config-cancel-btn", "n_clicks"),
    prevent_initial_call=True,
)
def _cancel_config(n):
    return False if n else no_update


@callback(
    Output("tech-chart",      "figure"),
    Output("tech-status",     "children"),
    Output("tech-chart-data", "data"),
    Input("tech-ticker",             "value"),
    Input("tech-active-interval",    "data"),
    Input("tech-indicators-store",   "data"),
    Input("tech-load-btn",           "n_clicks"),
    Input("tech-fill-between-store", "data"),
    Input("tech-strategy-store",     "data"),
)
def _update_chart(ticker, interval_key, indicators, _load, fill_betweens, strategy_store):
    ticker       = (ticker or "AAPL").strip().upper()
    interval_key = interval_key or _DEFAULT_IV
    indicators   = indicators or []

    df = _fetch_ohlcv(ticker, interval_key)
    if df is None or df.empty:
        empty = go.Figure()
        empty.update_layout(
            paper_bgcolor=_BG, plot_bgcolor=_BG,
            xaxis=dict(visible=False), yaxis=dict(visible=False),
            annotations=[dict(
                text=f"No data for  <b>{ticker}</b>",
                showarrow=False, font=dict(color="#888888", size=15),
                xref="paper", yref="paper", x=0.5, y=0.5,
            )],
            margin=dict(l=10, r=10, t=10, b=10),
        )
        return empty, f"Could not load data for {ticker} ({interval_key}).", None

    computed_inds = [_compute_indicator(df, ind) for ind in indicators]

    # Extract signals from strategy store if length still matches current data
    signals = None
    if strategy_store and "signals" in strategy_store:
        raw = strategy_store["signals"]
        if len(raw) == len(df):
            signals = pd.Series(raw, index=df.index, dtype=int)

    fig = _build_figure(df, ticker, interval_key, computed_inds, fill_betweens or [],
                        signals=signals)

    intraday   = interval_key in _INTRADAY_IVS
    fmt        = "%Y-%m-%d %H:%M" if intraday else "%Y-%m-%d"
    dates_list = [d.strftime(fmt) for d in df.index]

    store: dict = {
        "ticker":        ticker,
        "interval":      interval_key,
        "intraday":      intraday,
        "dates":         dates_list,
        "date_to_idx":   {d[:16]: i for i, d in enumerate(dates_list)},
        "open":          [float(x) for x in df["Open"]],
        "high":          [float(x) for x in df["High"]],
        "low":           [float(x) for x in df["Low"]],
        "close":         [float(x) for x in df["Close"]],
        "computed_inds": computed_inds,
    }

    last_dt    = df.index[-1]
    last_close = float(df["Close"].iloc[-1])
    prev_close = float(df["Close"].iloc[-2]) if len(df) > 1 else last_close
    chg        = last_close - prev_close
    chg_pct    = chg / prev_close * 100 if prev_close else 0
    sign       = "+" if chg >= 0 else ""
    status = (
        f"{ticker}  ·  {interval_key}  ·  {len(df)} bars  ·  "
        f"Last: ${last_close:.2f}  ({sign}{chg:.2f} / {sign}{chg_pct:.2f}%)"
        f"  ·  {last_dt.strftime(fmt)}"
    )
    return fig, status, store


@callback(
    Output("tech-hover-info", "children"),
    Input("tech-chart",       "hoverData"),
    State("tech-chart-data",  "data"),
    prevent_initial_call=True,
)
def _update_hover_info(hover_data, store):
    if not hover_data or not store:
        return []
    pts = hover_data.get("points", [])
    if not pts:
        return []

    idx = None
    for pt in pts:
        raw = pt.get("customdata")
        if raw is not None:
            try:
                idx = int(raw[0]) if isinstance(raw, list) else int(raw)
            except (TypeError, ValueError):
                pass
            break
    if idx is None:
        return []

    dates = store.get("dates", [])
    if idx >= len(dates):
        return []

    date_str = dates[idx]
    o = store["open"][idx]; h = store["high"][idx]
    l = store["low"][idx];  c = store["close"][idx]

    computed_inds = store.get("computed_inds", [])
    # Price card includes all non-VOLMA indicator values
    price_inds = [ci for ci in computed_inds if ci["type"] != "VOLMA"]
    cards = [_price_card(date_str, o, h, l, c,
                         computed_inds=price_inds, idx=idx)]

    vol_ind = next((ci for ci in computed_inds if ci["type"] == "VOLMA"), None)
    if vol_ind and "volume" in vol_ind and idx < len(vol_ind["volume"]):
        v      = float(vol_ind["volume"][idx])
        vma    = float(vol_ind["vol_ma"][idx]) if idx < len(vol_ind["vol_ma"]) else None
        vp     = vol_ind["vol_pct"][idx]
        vz     = vol_ind["vol_zscore"][idx]
        vol_color = vol_ind.get("style", {}).get("color_basis", vol_ind["color"])
        cards.append(_vol_card(
            v, vma, vol_ind["params"].get("period", 20),
            color=vol_color,
            vol_pct=float(vp)    if vp is not None else None,
            vol_zscore=float(vz) if vz is not None else None,
        ))
    return cards


# ---------------------------------------------------------------------------
# Color swatch callback (fix: swatch updates when color dropdown changes)
# ---------------------------------------------------------------------------

@callback(
    Output({"type": "tech-cfg-color-swatch", "index": ALL}, "style"),
    Input({"type": "tech-cfg-color", "index": ALL}, "value"),
    prevent_initial_call=True,
)
def _update_config_color_swatches(color_vals):
    return [
        {"color": (c or "#888888"), "fontSize": "1.1rem",
         "marginRight": "6px", "lineHeight": 1}
        for c in color_vals
    ]


# ---------------------------------------------------------------------------
# Fill-between callbacks
# ---------------------------------------------------------------------------

@callback(
    Output("tech-fill-between-modal",      "is_open"),
    Output("tech-fill-between-modal-body", "children"),
    Input("tech-fill-between-open-btn",    "n_clicks"),
    State("tech-fill-between-store",       "data"),
    State("tech-indicators-store",         "data"),
    prevent_initial_call=True,
)
def _open_fill_between_modal(n, fill_betweens, indicators):
    if not n:
        return no_update, no_update
    opts = _fill_curve_options(indicators or [])
    return True, _build_fb_modal_body(fill_betweens or [], opts)


@callback(
    Output("tech-fill-between-store",       "data"),
    Output("tech-fill-between-modal-body",  "children", allow_duplicate=True),
    Input("tech-fill-between-add-btn",      "n_clicks"),
    State("tech-fill-between-store",        "data"),
    State("tech-indicators-store",          "data"),
    prevent_initial_call=True,
)
def _add_fill_between(n, fill_betweens, indicators):
    if not n:
        return no_update, no_update
    fill_betweens = list(fill_betweens or [])
    opts = _fill_curve_options(indicators or [])
    default = opts[0]["value"] if opts else ""
    new_fb = {
        "id":     f"fb-{int(time.time() * 1000)}",
        "curve1": default,
        "curve2": default,
        "color":  "#ffffff",
    }
    fill_betweens.append(new_fb)
    return fill_betweens, _build_fb_modal_body(fill_betweens, opts)


@callback(
    Output("tech-fill-between-store",       "data",     allow_duplicate=True),
    Output("tech-fill-between-modal-body",  "children", allow_duplicate=True),
    Input({"type": "tech-fb-remove", "index": ALL}, "n_clicks"),
    State("tech-fill-between-store",  "data"),
    State("tech-indicators-store",    "data"),
    prevent_initial_call=True,
)
def _remove_fill_between(clicks, fill_betweens, indicators):
    if not any(clicks):
        return no_update, no_update
    triggered = ctx.triggered_id
    if not triggered or not isinstance(triggered, dict):
        return no_update, no_update
    fb_id = triggered["index"]
    fill_betweens = [fb for fb in (fill_betweens or []) if fb["id"] != fb_id]
    opts = _fill_curve_options(indicators or [])
    return fill_betweens, _build_fb_modal_body(fill_betweens, opts)


@callback(
    Output("tech-fill-between-store",  "data",     allow_duplicate=True),
    Output("tech-fill-between-modal",  "is_open",  allow_duplicate=True),
    Input("tech-fill-between-save-btn", "n_clicks"),
    State("tech-fill-between-store",   "data"),
    State({"type": "tech-fb-curve1", "index": ALL}, "value"),
    State({"type": "tech-fb-curve1", "index": ALL}, "id"),
    State({"type": "tech-fb-curve2", "index": ALL}, "value"),
    State({"type": "tech-fb-curve2", "index": ALL}, "id"),
    State({"type": "tech-fb-color",  "index": ALL}, "value"),
    State({"type": "tech-fb-color",  "index": ALL}, "id"),
    prevent_initial_call=True,
)
def _save_fill_between(n, fill_betweens,
                       c1_vals, c1_ids, c2_vals, c2_ids,
                       color_vals, color_ids):
    if not n:
        return no_update, no_update
    updates: dict[str, dict] = {}
    for val, id_d in zip(c1_vals, c1_ids):
        updates.setdefault(id_d["index"], {})["curve1"] = val
    for val, id_d in zip(c2_vals, c2_ids):
        updates.setdefault(id_d["index"], {})["curve2"] = val
    for val, id_d in zip(color_vals, color_ids):
        updates.setdefault(id_d["index"], {})["color"] = val
    result = []
    for fb in (fill_betweens or []):
        patch = updates.get(fb["id"], {})
        result.append({**fb, **patch})
    return result, False


@callback(
    Output("tech-fill-between-modal", "is_open", allow_duplicate=True),
    Input("tech-fill-between-close-btn", "n_clicks"),
    prevent_initial_call=True,
)
def _close_fill_between_modal(n):
    return False if n else no_update


@callback(
    Output({"type": "tech-fb-color-swatch", "index": ALL}, "style"),
    Input({"type": "tech-fb-color", "index": ALL}, "value"),
    prevent_initial_call=True,
)
def _update_fb_color_swatches(color_vals):
    return [
        {"color": (c or "#888888"), "fontSize": "1.1rem",
         "marginRight": "4px", "lineHeight": 1}
        for c in color_vals
    ]


# ---------------------------------------------------------------------------
# Legend color swatch + auto-update callbacks
# ---------------------------------------------------------------------------

@callback(
    Output({"type": "tech-cfg-legend-swatch", "index": ALL}, "style"),
    Input({"type": "tech-cfg-legend-color", "index": ALL}, "value"),
    prevent_initial_call=True,
)
def _update_legend_color_swatch(vals):
    return [
        {"color": (v or "#888888"), "fontSize": "1.1rem",
         "marginRight": "6px", "lineHeight": 1}
        for v in vals
    ]


@callback(
    Output({"type": "tech-cfg-legend-color", "index": ALL}, "value"),
    Input({"type": "tech-cfg-color", "index": ALL}, "value"),
    State({"type": "tech-cfg-color", "index": ALL}, "id"),
    prevent_initial_call=True,
)
def _auto_update_legend_color(all_vals, all_ids):
    """Auto-set legend color to majority of basis/upper/lower whenever they change."""
    triggered = ctx.triggered_id
    if not isinstance(triggered, dict):
        return no_update
    triggered_key = triggered.get("index", "")
    if triggered_key not in ("color_basis", "color_upper", "color_lower"):
        return no_update
    color_map: dict[str, str] = {
        (id_d.get("index", "") if isinstance(id_d, dict) else ""): v
        for id_d, v in zip(all_ids, all_vals)
    }
    cb_v = color_map.get("color_basis", "")
    cu_v = color_map.get("color_upper", "")
    cl_v = color_map.get("color_lower", "")
    majority = _majority_color(cb_v, cu_v, cl_v)
    if not majority or majority == "none":
        return no_update
    # Output to ALL matching legend-color components (0 or 1 when modal open)
    return [majority]


# ---------------------------------------------------------------------------
# Save Preset callbacks
# ---------------------------------------------------------------------------

def _build_save_modal_body(indicators: list[dict]) -> html.Div:
    all_ids = [ind["id"] for ind in indicators]
    options = [
        {"label": _ind_full_label(ind), "value": ind["id"]}
        for ind in indicators
    ]
    default_name = "All Indicators" if len(indicators) != 1 else _ind_full_label(indicators[0])
    return html.Div([
        html.Div("Select indicators to save:",
                 style={"color": "#888888", "fontSize": "0.80rem", "marginBottom": "6px"}),
        dbc.Checklist(
            id="tech-save-ind-checklist",
            options=options,
            value=all_ids,
            style={"color": "#cccccc", "fontSize": "0.82rem"},
            className="mb-2",
        ),
        dbc.Checkbox(
            id="tech-save-include-fb",
            label="Include Fill Between (when saving all indicators)",
            value=True,
            style={"fontSize": "0.78rem"},
            className="mb-3",
        ),
        html.Div("Preset name:",
                 style={"color": "#888888", "fontSize": "0.80rem", "marginBottom": "4px"}),
        dbc.Input(
            id="tech-save-preset-name",
            placeholder="e.g. My Setup",
            value=default_name,
            size="sm",
            style=_INPUT_STYLE,
        ),
    ])


@callback(
    Output("tech-save-preset-modal",      "is_open"),
    Output("tech-save-preset-modal-body", "children"),
    Input("tech-save-preset-btn",         "n_clicks"),
    State("tech-indicators-store",        "data"),
    prevent_initial_call=True,
)
def _open_save_preset_modal(n, indicators):
    if not n:
        return no_update, no_update
    inds = indicators or []
    return True, _build_save_modal_body(inds)


@callback(
    Output("tech-save-preset-modal", "is_open", allow_duplicate=True),
    Input("tech-save-preset-cancel-btn", "n_clicks"),
    prevent_initial_call=True,
)
def _cancel_save_preset(n):
    return False if n else no_update


@callback(
    Output("tech-preset-download",        "data"),
    Output("tech-save-preset-modal",      "is_open", allow_duplicate=True),
    Input("tech-save-preset-download-btn", "n_clicks"),
    State("tech-save-ind-checklist",      "value"),
    State("tech-save-include-fb",         "checked"),
    State("tech-save-preset-name",        "value"),
    State("tech-indicators-store",        "data"),
    State("tech-fill-between-store",      "data"),
    prevent_initial_call=True,
)
def _download_preset(n, selected_ids, include_fb, name, indicators, fill_betweens):
    if not n:
        return no_update, no_update
    indicators = indicators or []
    selected_ids = selected_ids or []
    chosen = [ind for ind in indicators if ind["id"] in selected_ids]
    all_selected = len(chosen) == len(indicators) and len(indicators) > 0
    preset: dict = {
        "version": 1,
        "name": (name or "preset").strip(),
        "indicators": chosen,
    }
    if all_selected and include_fb:
        preset["fill_betweens"] = fill_betweens or []
    safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in preset["name"])
    filename = f"{safe_name or 'preset'}.json"
    return dict(content=json.dumps(preset, indent=2), filename=filename), False


# ---------------------------------------------------------------------------
# Preset Library callbacks (filesystem-based)
# ---------------------------------------------------------------------------

@callback(
    Output("tech-preset-select",  "options", allow_duplicate=True),
    Output("tech-preset-status",  "children", allow_duplicate=True),
    Input("tech-preset-save-btn", "n_clicks"),
    State("tech-preset-name-input", "value"),
    State("tech-indicators-store",  "data"),
    State("tech-fill-between-store", "data"),
    prevent_initial_call=True,
)
def _save_preset_to_library(n, name, indicators, fill_betweens):
    if not n:
        raise dash.exceptions.PreventUpdate
    name = (name or "").strip()
    if not name:
        return (no_update,
                dbc.Alert("Enter a preset name first.", color="warning",
                          style={"padding": "4px 10px", "fontSize": "0.72rem",
                                 "marginBottom": 0}))
    indicators = indicators or []
    preset = {
        "version": 1,
        "name": name,
        "indicators": indicators,
    }
    if fill_betweens:
        preset["fill_betweens"] = fill_betweens
    _save_preset(name, preset)
    opts = _preset_dropdown_options()
    status = html.Span(f'✓ Saved "{name}"',
                       style={"color": "#2ecc71", "fontSize": "0.70rem"})
    return opts, status


@callback(
    Output("tech-indicators-store",   "data",    allow_duplicate=True),
    Output("tech-fill-between-store", "data",    allow_duplicate=True),
    Output("tech-preset-status",      "children", allow_duplicate=True),
    Input("tech-preset-load-btn",     "n_clicks"),
    State("tech-preset-select",       "value"),
    prevent_initial_call=True,
)
def _load_preset_from_library(n, selected):
    if not n or not selected:
        raise dash.exceptions.PreventUpdate
    preset = _load_preset(selected)
    if preset is None:
        return (no_update, no_update,
                dbc.Alert(f'Preset "{selected}" not found.', color="danger",
                          style={"padding": "4px 10px", "fontSize": "0.72rem",
                                 "marginBottom": 0}))
    new_inds = preset.get("indicators", [])
    fb = preset.get("fill_betweens", None)
    fb_out = fb if fb is not None else no_update
    status = html.Span(f'✓ Loaded "{selected}"',
                       style={"color": "#4a90e2", "fontSize": "0.70rem"})
    return new_inds, fb_out, status


@callback(
    Output("tech-preset-select",  "options", allow_duplicate=True),
    Output("tech-preset-select",  "value"),
    Output("tech-preset-status",  "children", allow_duplicate=True),
    Input("tech-preset-delete-btn", "n_clicks"),
    State("tech-preset-select",     "value"),
    prevent_initial_call=True,
)
def _delete_preset_from_library(n, selected):
    if not n or not selected:
        raise dash.exceptions.PreventUpdate
    deleted = _delete_preset(selected)
    opts = _preset_dropdown_options()
    if deleted:
        status = html.Span(f'✓ Deleted "{selected}"',
                           style={"color": "#e74c3c", "fontSize": "0.70rem"})
    else:
        status = dbc.Alert(f'Preset "{selected}" not found.', color="warning",
                           style={"padding": "4px 10px", "fontSize": "0.72rem",
                                  "marginBottom": 0})
    return opts, None, status


# ---------------------------------------------------------------------------
# Strategy callbacks
# ---------------------------------------------------------------------------

@callback(
    Output("tech-strategy-select", "options", allow_duplicate=True),
    Input("tech-strategy-reload-btn", "n_clicks"),
    prevent_initial_call=True,
)
def _reload_strategy_options(n):
    """Refresh the strategy dropdown from disk (for newly added user strategies)."""
    if not n:
        return no_update
    return _strategy_dropdown_options()


@callback(
    Output("tech-strategy-param-panel", "children"),
    Input("tech-strategy-select", "value"),
    prevent_initial_call=True,
)
def _strategy_param_panel(selected):
    """Build the parameter form when a strategy is selected."""
    if not selected:
        return []
    strategies = list_strategies()
    info = next((s for s in strategies if s["name"] == selected), None)
    if info is None:
        return []
    try:
        module = load_strategy(selected, is_builtin=info["is_builtin"])
    except StrategyError:
        return []
    params_spec = getattr(module, "PARAMS", {})
    return _build_strategy_param_form(params_spec)


@callback(
    Output("tech-strategy-store",     "data"),
    Output("tech-strategy-perf-card", "children"),
    Output("tech-indicators-store",   "data",    allow_duplicate=True),
    Output("tech-fill-between-store", "data",    allow_duplicate=True),
    Input("tech-strategy-run-btn",    "n_clicks"),
    State("tech-strategy-select",     "value"),
    State("tech-chart-data",          "data"),
    State({"type": "tech-strat-num", "index": ALL}, "value"),
    State({"type": "tech-strat-num", "index": ALL}, "id"),
    State({"type": "tech-strat-dd",  "index": ALL}, "value"),
    State({"type": "tech-strat-dd",  "index": ALL}, "id"),
    prevent_initial_call=True,
)
def _run_strategy(n, selected, chart_data,
                  num_vals, num_ids, dd_vals, dd_ids):
    _err_style = {"padding": "4px 10px", "fontSize": "0.72rem", "marginBottom": 0}

    if not n or not selected:
        return no_update, no_update, no_update, no_update

    if not chart_data:
        return (no_update,
                dbc.Alert("Load chart data first.", color="warning", style=_err_style),
                no_update, no_update)

    # Collect parameters from form
    params: dict = {}
    for val, id_d in zip(num_vals, num_ids):
        if val is not None:
            params[id_d["index"]] = val
    for val, id_d in zip(dd_vals, dd_ids):
        if val is not None:
            params[id_d["index"]] = val

    # Reconstruct DataFrame from chart store
    try:
        dates = pd.to_datetime(chart_data["dates"])
        df = pd.DataFrame(
            {
                "Open":   chart_data["open"],
                "High":   chart_data["high"],
                "Low":    chart_data["low"],
                "Close":  chart_data["close"],
            },
            index=dates,
        )
    except Exception as exc:
        return (no_update,
                dbc.Alert(f"Could not rebuild chart data: {exc}",
                          color="danger", style=_err_style),
                no_update, no_update)

    # Find strategy metadata
    strategies = list_strategies()
    info = next((s for s in strategies if s["name"] == selected), None)
    if info is None:
        return (no_update,
                dbc.Alert(f'Strategy "{selected}" not found.',
                          color="danger", style=_err_style),
                no_update, no_update)

    # Load and run
    try:
        module = load_strategy(selected, is_builtin=info["is_builtin"])
        result = run_strategy(
            df,
            chart_data.get("ticker", ""),
            chart_data.get("interval", ""),
            module,
            params,
            _get_source,
            _compute_ma,
            _compute_indicator,
        )
    except StrategyError as exc:
        return (no_update,
                dbc.Alert(str(exc), color="danger", style=_err_style),
                no_update, no_update)

    # Fetch SPY daily data for benchmark comparison (best-effort)
    spy_df = None
    try:
        spy_df = _fetch_ohlcv("SPY", "1D")
    except Exception:
        pass

    bt   = run_backtest(df, result.signals, spy_df=spy_df)
    perf = backtest_to_dict(bt)

    store = {
        "name":        selected,
        "signals":     result.signals.tolist(),
        "dates":       chart_data["dates"],
        "performance": perf,
    }

    # Auto-load chart bundle if the strategy declares one.
    # Always reset indicators/fill-betweens so stale indicators from a prior
    # strategy (or manual additions) are cleared before loading the new ones.
    bundle_inds = []
    bundle_fb   = []
    bundle = get_chart_bundle(module)
    if bundle:
        preset_name    = bundle.get("preset")
        loaded_preset  = False
        if preset_name:
            preset = _load_preset(preset_name)
            if preset:
                bundle_inds   = preset.get("indicators", [])
                bundle_fb     = preset.get("fill_betweens", [])
                loaded_preset = True
        if not loaded_preset and "indicators" in bundle:
            bundle_inds = bundle["indicators"]
            bundle_fb   = bundle.get("fill_betweens", [])

    return store, _build_perf_card(info["display_name"], perf), bundle_inds, bundle_fb


@callback(
    Output("tech-strategy-store",     "data",     allow_duplicate=True),
    Output("tech-strategy-perf-card", "children", allow_duplicate=True),
    Input("tech-strategy-clear-btn",  "n_clicks"),
    prevent_initial_call=True,
)
def _clear_strategy(n):
    if not n:
        return no_update, no_update
    return None, []


@callback(
    Output("tech-strategy-new-modal", "is_open"),
    Output("tech-strategy-new-path",  "children"),
    Input("tech-strategy-new-btn",    "n_clicks"),
    prevent_initial_call=True,
)
def _open_new_strategy_modal(n):
    if not n:
        return no_update, no_update
    return True, []


@callback(
    Output("tech-strategy-new-modal",  "is_open",  allow_duplicate=True),
    Output("tech-strategy-select",     "options",  allow_duplicate=True),
    Output("tech-strategy-new-path",   "children", allow_duplicate=True),
    Input("tech-strategy-create-btn",  "n_clicks"),
    State("tech-strategy-new-name",    "value"),
    prevent_initial_call=True,
)
def _create_new_strategy(n, name):
    _err_style = {"color": "#e74c3c", "fontSize": "0.74rem", "marginTop": "4px"}
    if not n:
        return no_update, no_update, no_update
    name = (name or "").strip()
    if not name:
        return (no_update, no_update,
                html.Span("Please enter a strategy name.", style=_err_style))
    try:
        slug = save_user_strategy(name)
    except Exception as exc:
        return (no_update, no_update,
                html.Span(f"Error: {exc}", style=_err_style))
    opts    = _strategy_dropdown_options()
    py_path = Path(__file__).resolve().parents[2] / "data" / "strategies" / f"{slug}.py"
    msg     = html.Span(
        f"Created: {py_path}  — edit then click Reload.",
        style={"color": "#2ecc71", "fontSize": "0.72rem"},
    )
    return False, opts, msg


@callback(
    Output("tech-strategy-new-modal",     "is_open",  allow_duplicate=True),
    Input("tech-strategy-new-cancel-btn", "n_clicks"),
    prevent_initial_call=True,
)
def _cancel_new_strategy(n):
    return False if n else no_update
