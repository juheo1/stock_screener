"""
frontend.strategy.data
======================
Shared OHLCV fetching and indicator computation helpers.

These functions are extracted from frontend/pages/technical.py so they can be
imported by both the Dash frontend and the backend scanner without any Dash
dependencies.

Public API
----------
INTERVAL_CFG            Interval key → yfinance config mapping
fetch_ohlcv             Fetch OHLCV DataFrame from yfinance
get_source              Extract a named price series from a DataFrame
compute_ma              Compute a moving average series
compute_vol_stats       Compute volume statistics (MA, percentile, z-score)
compute_indicator       Compute a full indicator from a spec dict
get_fb_curve            Resolve a fill-between curve reference
hex_to_rgba             Convert hex color to rgba string
ind_full_label          Generate full label string for an indicator spec
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Interval configuration
# ---------------------------------------------------------------------------

INTERVAL_CFG: dict[str, dict] = {
    "1MIN":  {"yf_interval": "1m",  "yf_period": "7d",   "resample": None},
    "2MIN":  {"yf_interval": "2m",  "yf_period": "60d",  "resample": None},
    "5MIN":  {"yf_interval": "5m",  "yf_period": "60d",  "resample": None},
    "15MIN": {"yf_interval": "15m", "yf_period": "60d",  "resample": None},
    "30MIN": {"yf_interval": "30m", "yf_period": "60d",  "resample": None},
    "1H":    {"yf_interval": "1h",  "yf_period": "730d", "resample": None},
    "2H":    {"yf_interval": "1h",  "yf_period": "60d",  "resample": "2h"},
    "3H":    {"yf_interval": "1h",  "yf_period": "60d",  "resample": "3h"},
    "4H":    {"yf_interval": "1h",  "yf_period": "60d",  "resample": "4h"},
    "1D":    {"yf_interval": "1d",  "yf_period": "max",  "resample": None},
    "1W":    {"yf_interval": "1wk", "yf_period": "5y",   "resample": None},
    "1MON":  {"yf_interval": "1mo", "yf_period": "10y",  "resample": None},
    "3MON":  {"yf_interval": "1mo", "yf_period": "10y",  "resample": "QE"},
    "6MON":  {"yf_interval": "1mo", "yf_period": "15y",  "resample": "6ME"},
    "12MON": {"yf_interval": "1mo", "yf_period": "20y",  "resample": "YE"},
}

_IND_COLOR_POOL = [
    "#f0c040", "#40e0c0", "#f040a0", "#a07af0",
    "#f0a040", "#40a0f0", "#80f040", "#f07040",
    "#40f080", "#c040c0",
]


# ---------------------------------------------------------------------------
# OHLCV fetch
# ---------------------------------------------------------------------------

def fetch_ohlcv(ticker: str, interval_key: str) -> pd.DataFrame | None:
    """Fetch OHLCV data, preferring the local Parquet cache for daily bars.

    Cache-first logic:
    - ``"1D"``: read from ``OHLCVStore``; fall back to live fetch if missing or stale.
    - Intraday intervals: read from intraday archive if available, else live fetch.
    - All other intervals: live fetch (unchanged behaviour).

    Parameters
    ----------
    ticker:
        Symbol string, e.g. ``"AAPL"``.
    interval_key:
        One of the keys in :data:`INTERVAL_CFG`, e.g. ``"1D"``.

    Returns
    -------
    pd.DataFrame with columns Open/High/Low/Close/Volume, or ``None`` on failure.
    """
    # ── Cache-first path ────────────────────────────────────────────────────
    if interval_key == "1D":
        cached = _read_daily_cache(ticker)
        if cached is not None:
            return cached

    elif interval_key in ("1MIN", "5MIN"):
        cached = _read_intraday_cache(ticker, interval_key)
        if cached is not None:
            return cached

    # ── Live fetch fallback ─────────────────────────────────────────────────
    return _live_fetch(ticker, interval_key)


def _read_daily_cache(ticker: str) -> pd.DataFrame | None:
    """Try to read today's daily bars from the Parquet store."""
    try:
        from src.ohlcv.store import OHLCVStore
        from src.config import settings
        from datetime import datetime, timedelta

        store = OHLCVStore(settings.ohlcv_dir)
        df    = store.read_daily(ticker)
        if df is None or df.empty:
            return None

        # Only use the cache if it was synced recently enough
        last_updated = store.get_last_updated(ticker, "daily")
        if last_updated is None:
            return None
        age_hours = (datetime.utcnow() - last_updated).total_seconds() / 3600
        if age_hours > settings.ohlcv_daily_stale_hours:
            return None

        return df
    except Exception:
        return None


def _read_intraday_cache(ticker: str, interval_key: str) -> pd.DataFrame | None:
    """Try to read archived intraday bars from the Parquet store."""
    try:
        from src.ohlcv.store import OHLCVStore
        from src.config import settings
        from datetime import date, timedelta

        interval_map = {"1MIN": "1min", "5MIN": "5min"}
        interval = interval_map.get(interval_key)
        if interval is None:
            return None

        store = OHLCVStore(settings.ohlcv_dir)
        end   = date.today()
        start = end - timedelta(days=60)
        df = store.read_intraday_range(ticker, interval, start, end)
        if df is not None and not df.empty:
            return df
    except Exception:
        pass
    return None


def _live_fetch(ticker: str, interval_key: str) -> pd.DataFrame | None:
    """Original yfinance live fetch (fallback)."""
    import yfinance as yf

    cfg = INTERVAL_CFG.get(interval_key, INTERVAL_CFG["1D"])
    try:
        df = yf.Ticker(ticker).history(
            period=cfg["yf_period"], interval=cfg["yf_interval"]
        )
    except Exception:
        return None
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    if cfg["resample"]:
        try:
            df = (
                df.resample(cfg["resample"])
                .agg({"Open": "first", "High": "max",
                      "Low": "min", "Close": "last", "Volume": "sum"})
                .dropna()
            )
        except Exception:
            pass
    return df if not df.empty else None


# ---------------------------------------------------------------------------
# Price source extraction
# ---------------------------------------------------------------------------

def get_source(df: pd.DataFrame, source: str) -> pd.Series:
    """Extract a named price series from an OHLCV DataFrame.

    Supported names: ``Close``, ``Open``, ``High``, ``Low``,
    ``HL2``, ``HLC3``, ``OHLC4``.  Anything else falls back to Close.
    """
    if source == "Open":  return df["Open"]
    if source == "High":  return df["High"]
    if source == "Low":   return df["Low"]
    if source == "HL2":   return (df["High"] + df["Low"]) / 2
    if source == "HLC3":  return (df["High"] + df["Low"] + df["Close"]) / 3
    if source == "OHLC4": return (df["Open"] + df["High"] + df["Low"] + df["Close"]) / 4
    return df["Close"]


# ---------------------------------------------------------------------------
# Moving average
# ---------------------------------------------------------------------------

def compute_ma(src: pd.Series, ma_type: str, length: int) -> pd.Series:
    """Compute a moving average of the requested type.

    Supported types: ``SMA``, ``EMA``, ``WMA``, ``SMMA (RMA)``, ``RMA``.
    Unknown types fall back to SMA.
    """
    n = max(2, int(length))
    if ma_type == "EMA":
        return src.ewm(span=n, adjust=False).mean()
    if ma_type == "WMA":
        w = np.arange(1, n + 1, dtype=float)
        return src.rolling(n).apply(lambda x: float(np.dot(x, w) / w.sum()), raw=True)
    if ma_type in ("SMMA (RMA)", "RMA"):
        return src.ewm(alpha=1.0 / n, adjust=False).mean()
    return src.rolling(n, min_periods=1).mean()


# ---------------------------------------------------------------------------
# Volume statistics
# ---------------------------------------------------------------------------

def compute_vol_stats(
    vol: pd.Series, n: int
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """Compute volume statistics.

    Returns
    -------
    (vol_ma, vol_std, vol_pct, vol_zscore)
    """
    vol_ma  = vol.rolling(n, min_periods=1).mean()
    vol_std = vol.rolling(n, min_periods=2).std()
    vol_pct = vol.rank(pct=True) * 100
    vol_z   = (vol - vol_ma) / vol_std.replace(0, np.nan)
    return vol_ma, vol_std, vol_pct, vol_z


# ---------------------------------------------------------------------------
# Hex → rgba
# ---------------------------------------------------------------------------

def hex_to_rgba(hex_color: str, alpha: float = 0.06) -> str:
    """Convert a hex colour string to an ``rgba(...)`` CSS value."""
    h = hex_color.lstrip("#")
    if len(h) == 6:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgba({r},{g},{b},{alpha})"
    return f"rgba(120,120,120,{alpha})"


# ---------------------------------------------------------------------------
# Indicator label helpers
# ---------------------------------------------------------------------------

def _src_short(s: str) -> str:
    return {"Close": "C", "Open": "O", "High": "H", "Low": "L"}.get(s, s)


def ind_full_label(ind: dict) -> str:
    """Generate the full human-readable label for an indicator spec dict."""
    t = ind["type"]
    p = ind["params"]
    src = _src_short(p.get("source", "Close"))
    if t == "SMA":   return f"SMA ({p.get('period', 50)}, {src})"
    if t == "EMA":   return f"EMA ({p.get('period', 21)}, {src})"
    if t == "BB":
        return (f"BB ({p.get('length', 20)}, {p.get('ma_type', 'SMA')}, "
                f"{src}, {p.get('stddev', 2.0)}, {p.get('offset', 0)})")
    if t == "DC":    return f"DC ({p.get('period', 20)})"
    if t == "VOLMA": return f"Vol MA ({p.get('period', 20)})"
    return t


# ---------------------------------------------------------------------------
# Indicator computation
# ---------------------------------------------------------------------------

def compute_indicator(df: pd.DataFrame, ind: dict) -> dict:
    """Compute series for one indicator spec.

    Returns an enriched copy of *ind* with computed data fields added.

    Supported types:  ``SMA``, ``EMA``, ``BB``, ``DC``, ``VOLMA``.

    SMA / EMA add a ``values`` list.
    BB / DC add ``upper``, ``mid``, ``lower`` lists.
    VOLMA adds ``volume``, ``vol_ma``, ``vol_pct``, ``vol_zscore`` lists.
    """
    t      = ind["type"]
    p      = ind["params"]
    color  = ind.get("color", _IND_COLOR_POOL[0])
    style  = ind.get("style", {
        "color_basis": color, "color_upper": color,
        "color_lower": color, "color_legend": color,
    })
    result = {
        "id": ind["id"], "type": t, "color": color,
        "params": p, "style": style,
        "full_label": ind_full_label(ind),
    }

    if t == "SMA":
        src = get_source(df, p.get("source", "Close"))
        n   = max(2, int(p.get("period", 50)))
        result["values"] = src.rolling(n, min_periods=1).mean().tolist()

    elif t == "EMA":
        src = get_source(df, p.get("source", "Close"))
        n   = max(2, int(p.get("period", 21)))
        result["values"] = src.ewm(span=n, adjust=False).mean().tolist()

    elif t == "BB":
        length  = max(2, int(p.get("length", 20)))
        ma_type = p.get("ma_type", "SMA")
        source  = p.get("source", "Close")
        stddev  = max(0.1, float(p.get("stddev", 2.0)))
        offset  = int(p.get("offset", 0))
        src     = get_source(df, source)
        basis   = compute_ma(src, ma_type, length)
        std     = src.rolling(length, min_periods=2).std().fillna(0)
        upper   = basis + stddev * std
        lower   = basis - stddev * std
        if offset:
            upper = upper.shift(offset)
            lower = lower.shift(offset)
            basis = basis.shift(offset)
        result["upper"] = upper.tolist()
        result["mid"]   = basis.tolist()
        result["lower"] = lower.tolist()

    elif t == "DC":
        n = max(2, int(p.get("period", 20)))
        upper = df["High"].shift(1).rolling(n).max()
        lower = df["Low"].shift(1).rolling(n).min()
        mid   = (upper + lower) / 2
        result["upper"] = upper.tolist()
        result["mid"]   = mid.tolist()
        result["lower"] = lower.tolist()

    elif t == "VOLMA":
        n = max(2, int(p.get("period", 20)))
        vol_ma, _, vol_pct, vol_z = compute_vol_stats(df["Volume"], n)
        result["volume"]     = df["Volume"].tolist()
        result["vol_ma"]     = vol_ma.tolist()
        result["vol_pct"]    = [
            float(x) if not math.isnan(float(x)) else None for x in vol_pct
        ]
        result["vol_zscore"] = [
            float(x) if not math.isnan(float(x)) else None for x in vol_z
        ]

    return result


# ---------------------------------------------------------------------------
# Fill-between curve resolver
# ---------------------------------------------------------------------------

def get_fb_curve(computed_inds: list[dict], curve_ref: str) -> list | None:
    """Resolve a fill-between curve reference to its data list.

    *curve_ref* format: ``"{indicator_id}:{field}"``, e.g.
    ``"bb-abc123:lower"``.

    Returns the matching list of values, or ``None`` if not found.
    """
    parts = curve_ref.split(":", 1)
    if len(parts) != 2:
        return None
    ind_id, field = parts
    ci = next((c for c in computed_inds if c["id"] == ind_id), None)
    if ci and field in ci:
        return ci[field]
    return None
