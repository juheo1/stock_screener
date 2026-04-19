"""
frontend.strategy.chart
=======================
Shared Plotly figure builder for the Technical Chart and the Scanner drill-down.

Extracted from frontend/pages/technical.py so it can be imported from both
the Dash frontend and backend contexts.

Public API
----------
build_figure    Build a Plotly candlestick figure with indicators and signals.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from frontend.strategy.data import get_fb_curve, hex_to_rgba

# ---------------------------------------------------------------------------
# Colour constants (shared with technical.py)
# ---------------------------------------------------------------------------

C_UP         = "#26a69a"
C_DOWN       = "#ef5350"
BG           = "#000000"
GRID         = "#1c1c1c"
AX           = "#666666"
C_STRAT_BUY  = "#00e676"
C_STRAT_SELL = "#ff1744"
MARKER_OFFSET = 0.005

INTRADAY_IVS = {"1MIN", "2MIN", "5MIN", "15MIN", "30MIN", "1H", "2H", "3H", "4H"}
DAILY_PLUS   = {"1D", "1W", "1MON", "3MON", "6MON", "12MON"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _majority_color(cb: str, cu: str, cl: str, fallback: str = "#888888") -> str:
    """Return the most common non-'none' color among basis/upper/lower."""
    candidates = [c for c in [cb, cu, cl] if c and c != "none"]
    if not candidates:
        return fallback
    freq: dict[str, int] = {}
    for c in candidates:
        freq[c] = freq.get(c, 0) + 1
    max_count = max(freq.values())
    majority_opts = [c for c, n in freq.items() if n == max_count]
    return cb if (cb in majority_opts and cb != "none") else majority_opts[0]


# ---------------------------------------------------------------------------
# Figure builder
# ---------------------------------------------------------------------------

def build_figure(
    df: pd.DataFrame,
    ticker: str,
    interval_key: str,
    computed_inds: list[dict],
    fill_betweens: list[dict] | None = None,
    signals: pd.Series | None = None,
) -> go.Figure:
    """Build a Plotly candlestick figure with indicator overlays and signal markers.

    Parameters
    ----------
    df:
        OHLCV DataFrame with a DatetimeIndex.
    ticker:
        Ticker symbol shown in the chart title and hover labels.
    interval_key:
        Interval string used to configure rangebreaks (e.g. ``"1D"``).
    computed_inds:
        List of computed indicator dicts from :func:`~frontend.strategy.data.compute_indicator`.
    fill_betweens:
        Optional list of fill-between spec dicts.
    signals:
        Optional pd.Series of integer signals (1=BUY, -1=SELL, 0=HOLD)
        aligned to df.index.  Used to overlay buy/sell markers.

    Returns
    -------
    plotly.graph_objects.Figure
    """
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
    for o_, h_, l_, c_ in zip(df["Open"], df["High"], df["Low"], df["Close"]):
        o_, h_, l_, c_ = float(o_), float(h_), float(l_), float(c_)
        up  = c_ >= o_
        arr = "▲" if up else "▼"
        cc  = C_UP if up else C_DOWN
        probe_custom.append((
            f"<span style='color:{AX}'>O </span>"
            f"<span style='color:#cccccc'>{o_:.2f}</span>  "
            f"<span style='color:{AX}'>H </span>"
            f"<span style='color:{C_UP}'>{h_:.2f}</span>  "
            f"<span style='color:{AX}'>L </span>"
            f"<span style='color:{C_DOWN}'>{l_:.2f}</span>  "
            f"<span style='color:{AX}'>C </span>"
            f"<span style='color:{cc}'>{arr} {c_:.2f}</span>"
        ))

    fig.add_trace(go.Scatter(
        x=df.index, y=df["High"], mode="lines",
        line=dict(color="rgba(0,0,0,0)", width=1),
        customdata=probe_custom,
        hovertemplate=(
            f"<b style='color:#ffffff'>{ticker}</b><br>%{{customdata}}<extra></extra>"
        ),
        showlegend=False, name="",
    ), row=1, col=1)

    # ── Per-indicator price-panel traces ─────────────────────────────
    for ci in computed_inds:
        t     = ci["type"]
        style = ci.get("style", {})
        color = ci.get("color", "#888888")
        cb    = style.get("color_basis", color)
        cu    = style.get("color_upper", color)
        cl    = style.get("color_lower", color)
        grp   = ci["id"]
        lbl   = ci["full_label"]

        if t == "SMA":
            if cb != "none":
                fig.add_trace(go.Scatter(
                    x=df.index, y=ci["values"], mode="lines",
                    name=lbl, legendgroup=grp, showlegend=True,
                    line=dict(color=cb, width=1.5), hoverinfo="skip",
                ), row=1, col=1)

        elif t == "EMA":
            if cb != "none":
                fig.add_trace(go.Scatter(
                    x=df.index, y=ci["values"], mode="lines",
                    name=lbl, legendgroup=grp, showlegend=True,
                    line=dict(color=cb, width=1.5, dash="dot"), hoverinfo="skip",
                ), row=1, col=1)

        elif t == "BB":
            has_visible = any(c != "none" for c in [cb, cu, cl])
            if has_visible:
                legend_c = style.get("color_legend") or _majority_color(cb, cu, cl)
                if not legend_c or legend_c == "none":
                    legend_c = next((c for c in [cb, cu, cl] if c != "none"), "#888888")
                fig.add_trace(go.Scatter(
                    x=[None], y=[None], mode="lines",
                    name=lbl, legendgroup=grp, showlegend=True,
                    line=dict(color=legend_c, width=1.5), hoverinfo="skip",
                ), row=1, col=1)
            if cu != "none":
                fig.add_trace(go.Scatter(
                    x=df.index, y=ci["upper"], mode="lines",
                    name=lbl, legendgroup=grp, showlegend=False,
                    line=dict(color=cu, width=1.0), hoverinfo="skip",
                ), row=1, col=1)
            if cl != "none":
                fig.add_trace(go.Scatter(
                    x=df.index, y=ci["lower"], mode="lines",
                    name=lbl, legendgroup=grp, showlegend=False,
                    line=dict(color=cl, width=1.0), hoverinfo="skip",
                ), row=1, col=1)
            if cb != "none":
                fig.add_trace(go.Scatter(
                    x=df.index, y=ci["mid"], mode="lines",
                    name=lbl, legendgroup=grp, showlegend=False,
                    line=dict(color=cb, width=1.0, dash="dot"), hoverinfo="skip",
                ), row=1, col=1)

        elif t == "DC":
            has_visible = any(c != "none" for c in [cb, cu, cl])
            if has_visible:
                legend_c = style.get("color_legend") or _majority_color(cb, cu, cl)
                if not legend_c or legend_c == "none":
                    legend_c = next((c for c in [cb, cu, cl] if c != "none"), "#888888")
                fig.add_trace(go.Scatter(
                    x=[None], y=[None], mode="lines",
                    name=lbl, legendgroup=grp, showlegend=True,
                    line=dict(color=legend_c, width=1.5), hoverinfo="skip",
                ), row=1, col=1)
            if cu != "none":
                fig.add_trace(go.Scatter(
                    x=df.index, y=ci["upper"], mode="lines",
                    name=lbl, legendgroup=grp, showlegend=False,
                    line=dict(color=cu, width=1.2), hoverinfo="skip",
                ), row=1, col=1)
            if cl != "none":
                fill_color = hex_to_rgba(cl, 0.06)
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
                    line=dict(color=cb, width=0.8, dash="dash"), hoverinfo="skip",
                ), row=1, col=1)

    # ── Fill-between traces ───────────────────────────────────────────
    for fb in (fill_betweens or []):
        c1_ref = fb.get("curve1")
        c2_ref = fb.get("curve2")
        color  = fb.get("color", "#ffffff")
        if not c1_ref or not c2_ref:
            continue
        y1 = get_fb_curve(computed_inds, c1_ref)
        y2 = get_fb_curve(computed_inds, c2_ref)
        if y1 is None or y2 is None:
            continue
        fill_color = hex_to_rgba(color, 0.15)
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
        increasing=dict(line=dict(color=C_UP,   width=1), fillcolor=C_UP),
        decreasing=dict(line=dict(color=C_DOWN, width=1), fillcolor=C_DOWN),
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
                y=df["Low"][buy_mask] * (1 - MARKER_OFFSET),
                mode="markers",
                marker=dict(
                    symbol="triangle-up", size=10, color=C_STRAT_BUY,
                    line=dict(color=C_STRAT_BUY, width=1),
                ),
                name="Buy", legendgroup="strategy-signals", showlegend=True,
                hovertemplate="<b>BUY</b><br>%{x}<extra></extra>",
            ), row=1, col=1)
        if sell_mask.any():
            fig.add_trace(go.Scatter(
                x=df.index[sell_mask],
                y=df["High"][sell_mask] * (1 + MARKER_OFFSET),
                mode="markers",
                marker=dict(
                    symbol="triangle-down", size=10, color=C_STRAT_SELL,
                    line=dict(color=C_STRAT_SELL, width=1),
                ),
                name="Sell", legendgroup="strategy-signals", showlegend=True,
                hovertemplate="<b>SELL</b><br>%{x}<extra></extra>",
            ), row=1, col=1)

    # ── Volume subplot ───────────────────────────────────────────────
    if show_volume and vol_ind:
        vol_colors = [
            C_UP if float(c_) >= float(o_) else C_DOWN
            for c_, o_ in zip(df["Close"], df["Open"])
        ]
        fig.add_trace(go.Bar(
            x=df.index, y=vol_ind["volume"],
            name="Volume",
            marker=dict(color=vol_colors, line=dict(width=0)),
            opacity=0.65, showlegend=False, hoverinfo="skip",
        ), row=2, col=1)

        vol_color = vol_ind.get("style", {}).get("color_basis", vol_ind["color"])
        vol_lbl   = vol_ind["full_label"]
        if vol_color != "none":
            fig.add_trace(go.Scatter(
                x=df.index, y=vol_ind["vol_ma"], mode="lines",
                name=vol_lbl, legendgroup=vol_ind["id"], showlegend=True,
                line=dict(color=vol_color, width=1.5), hoverinfo="skip",
            ), row=2, col=1)

    # ── Layout ──────────────────────────────────────────────────────
    fig.update_layout(
        paper_bgcolor=BG, plot_bgcolor=BG,
        font=dict(color=AX, size=11,
                  family="'Inter', 'Segoe UI', system-ui, sans-serif"),
        title=dict(
            text=(f"<b>{ticker}</b>"
                  f"  <span style='color:{AX};font-size:13px'>{interval_key}</span>"),
            font=dict(color="#ffffff", size=14),
            x=0.005, xanchor="left",
        ),
        legend=dict(
            bgcolor="rgba(17,17,17,0.85)", bordercolor=GRID, borderwidth=1,
            font=dict(color="#cccccc", size=11),
            orientation="h", y=1.02, x=0, yanchor="bottom",
        ),
        margin=dict(l=10, r=70, t=46, b=36),
        hovermode="x unified", spikedistance=-1, hoverdistance=-1,
        hoverlabel=dict(
            bgcolor="#111111", bordercolor=GRID,
            font=dict(color="#ffffff", size=11), namelength=-1,
        ),
    )

    if interval_key in DAILY_PLUS:
        rb = [dict(bounds=["sat", "mon"])]
    elif interval_key in INTRADAY_IVS:
        rb = [dict(bounds=["sat", "mon"]), dict(bounds=[16, 9.5], pattern="hour")]
    else:
        rb = []

    fig.update_xaxes(
        gridcolor=GRID, linecolor=GRID,
        tickfont=dict(color=AX, size=10),
        rangeslider=dict(visible=False), rangebreaks=rb,
        showgrid=True, zeroline=False,
        showspikes=True, spikecolor="#555555",
        spikemode="across", spikethickness=1, spikedash="dot", spikesnap="cursor",
    )
    fig.update_yaxes(
        gridcolor=GRID, linecolor=GRID,
        tickfont=dict(color=AX, size=10),
        side="right", showgrid=True, zeroline=False,
        row=1, col=1,
    )
    if show_volume:
        fig.update_yaxes(
            gridcolor=GRID, linecolor=GRID,
            tickfont=dict(color=AX, size=9), tickformat=".2s",
            title_text="Vol", title_font=dict(color=AX, size=9),
            side="right", showgrid=True, zeroline=False,
            row=2, col=1,
        )
    return fig
