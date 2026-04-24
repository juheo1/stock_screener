"""
src.scanner.intraday_monitor
============================
Continuous intraday strategy monitor.

Runs a polling loop during market hours, fetching the latest 1-minute bars
for a configurable watchlist and evaluating intraday strategies on each new
bar.  New signals are persisted to ``intraday_signals`` and pushed to an
in-memory queue for the frontend to poll.

Public API
----------
IntradayMonitor     The monitor class (start/stop/status lifecycle).
get_monitor         Return the process-singleton instance.
"""
from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timezone
from queue import Empty, Queue
from typing import Any, Optional

import pandas as pd

from src.ohlcv.store import OHLCVStore
from src.ohlcv.fetcher import OHLCVFetcher
from src.config import settings

logger = logging.getLogger(__name__)

# Maximum signals to keep in the in-memory queue (oldest are discarded)
_QUEUE_MAXSIZE = 1000

# Market hours (ET) for automatic stop/skip logic
_MARKET_OPEN_ET  = (9, 30)   # 09:30
_MARKET_CLOSE_ET = (16, 0)   # 16:00


class IntradayMonitor:
    """Poll yfinance for 1-minute bars and run intraday strategies continuously.

    Lifecycle::

        monitor = IntradayMonitor(watchlist=["AAPL", "TSLA"], ...)
        monitor.start()
        # ... frontend polls monitor.get_recent_signals() ...
        monitor.stop()
    """

    def __init__(
        self,
        watchlist: list[str] | None = None,
        strategy_slugs: list[str] | None = None,
        poll_interval: int | None = None,
    ) -> None:
        self._store   = OHLCVStore(settings.ohlcv_dir)
        self._fetcher = OHLCVFetcher(self._store)

        self._watchlist: list[str]        = [t.upper() for t in (watchlist or [])]
        self._strategy_slugs: list[str] | None = strategy_slugs
        self._poll_interval: int          = poll_interval or settings.intraday_poll_interval

        # In-memory state
        self._buffers:      dict[str, pd.DataFrame] = {}   # ticker → today's 1m bars
        self._last_signals: dict[str, dict]         = {}   # ticker → {slug: last_value}
        self._signal_queue: Queue                   = Queue(maxsize=_QUEUE_MAXSIZE)
        self._signal_log:   list[dict]              = []   # persistent log for /signals

        # Thread management
        self._thread:     Optional[threading.Thread] = None
        self._stop_event: threading.Event            = threading.Event()
        self._state:      str                        = "stopped"  # stopped | running | stopping
        self._last_poll:  Optional[datetime]         = None
        self._signal_count: int                      = 0
        self._lock: threading.Lock                   = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the polling loop in a background daemon thread."""
        with self._lock:
            if self._state == "running":
                logger.info("[IntradayMonitor] Already running.")
                return
            self._stop_event.clear()
            self._state = "running"

        self._thread = threading.Thread(
            target=self._poll_loop,
            daemon=True,
            name="intraday-monitor",
        )
        self._thread.start()
        logger.info(
            "[IntradayMonitor] Started. watchlist=%s, poll_interval=%ds",
            self._watchlist, self._poll_interval,
        )

    def stop(self) -> None:
        """Signal the polling loop to stop gracefully."""
        with self._lock:
            if self._state == "stopped":
                return
            self._state = "stopping"
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._poll_interval + 10)
        with self._lock:
            self._state = "stopped"
        logger.info("[IntradayMonitor] Stopped.")

    def status(self) -> dict:
        """Return a status snapshot."""
        with self._lock:
            return {
                "state":        self._state,
                "watchlist":    list(self._watchlist),
                "strategies":   list(self._strategy_slugs or []),
                "poll_interval": self._poll_interval,
                "last_poll":    self._last_poll.isoformat() if self._last_poll else None,
                "signal_count": self._signal_count,
            }

    def update_watchlist(self, tickers: list[str]) -> None:
        """Replace the watchlist (takes effect on the next poll cycle)."""
        with self._lock:
            self._watchlist = [t.upper() for t in tickers]
        logger.info("[IntradayMonitor] Watchlist updated: %s", self._watchlist)

    def get_recent_signals(self, since: Optional[datetime] = None) -> list[dict]:
        """Return signals emitted after *since* (or all if None)."""
        with self._lock:
            log = list(self._signal_log)
        if since is None:
            return log
        return [s for s in log if _parse_dt(s.get("signal_time")) > since]

    def get_live_chart_data(self, ticker: str) -> Optional[dict]:
        """Return today's buffered 1-minute bars for *ticker* as a JSON-ready dict."""
        ticker = ticker.upper()
        with self._lock:
            df = self._buffers.get(ticker)
        if df is None or df.empty:
            # Try reading from the live checkpoint on disk
            df = self._store.read_live(ticker)
        if df is None or df.empty:
            return None
        return {
            "ticker": ticker,
            "timestamps": [str(ts) for ts in df.index],
            "open":   df["Open"].tolist()   if "Open"   in df.columns else [],
            "high":   df["High"].tolist()   if "High"   in df.columns else [],
            "low":    df["Low"].tolist()    if "Low"    in df.columns else [],
            "close":  df["Close"].tolist()  if "Close"  in df.columns else [],
            "volume": df["Volume"].tolist() if "Volume" in df.columns else [],
        }

    # ------------------------------------------------------------------
    # Internal polling loop
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        import time as _time

        logger.info("[IntradayMonitor] Poll loop started.")
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception as exc:
                logger.error("[IntradayMonitor] Poll error: %s", exc, exc_info=True)

            self._stop_event.wait(timeout=self._poll_interval)

        logger.info("[IntradayMonitor] Poll loop exited.")

    def _poll_once(self) -> None:
        with self._lock:
            watchlist = list(self._watchlist)

        if not watchlist:
            return

        now = datetime.now(timezone.utc)
        last = self._last_poll

        # Fetch new bars
        try:
            new_bars = self._fetcher.fetch_live_bars(watchlist, since=last)
        except Exception as exc:
            logger.warning("[IntradayMonitor] fetch_live_bars failed: %s", exc)
            return

        self._last_poll = now

        # Load strategies once per poll
        strategies = self._load_intraday_strategies()
        if not strategies:
            return

        for ticker, df in new_bars.items():
            if df is None or df.empty:
                continue

            # Merge into in-memory buffer
            with self._lock:
                existing = self._buffers.get(ticker)
                if existing is None or existing.empty:
                    # Seed buffer from disk if available
                    existing = self._store.read_live(ticker)
                merged = _append_new_bars(existing, df)
                self._buffers[ticker] = merged

            # Persist live checkpoint
            try:
                self._store.write_live(ticker, merged)
            except Exception as exc:
                logger.debug("[IntradayMonitor] write_live failed for %s: %s", ticker, exc)

            # Evaluate strategies
            self._evaluate_strategies(ticker, merged, strategies, now)

    def _evaluate_strategies(
        self,
        ticker: str,
        df: pd.DataFrame,
        strategies: list[Any],
        poll_time: datetime,
    ) -> None:
        from frontend.strategy.engine import run_strategy
        from frontend.strategy.data import get_source, compute_ma, compute_indicator

        for mod in strategies:
            slug = getattr(mod, "SLUG", getattr(mod, "__name__", "unknown"))
            params = {k: v["default"] for k, v in getattr(mod, "PARAMS", {}).items()}

            try:
                result = run_strategy(
                    df=df,
                    ticker=ticker,
                    interval="1MIN",
                    strategy_module=mod,
                    params=params,
                    get_source_fn=get_source,
                    compute_ma_fn=compute_ma,
                    compute_indicator_fn=compute_indicator,
                )
            except Exception as exc:
                logger.debug("[IntradayMonitor] Strategy %s/%s failed: %s", slug, ticker, exc)
                continue

            if result.signals is None or result.signals.empty:
                continue

            latest_signal = int(result.signals.iloc[-1])
            prev_key = (ticker, slug)
            prev_signal = self._last_signals.get(ticker, {}).get(slug, 0)

            if latest_signal != 0 and latest_signal != prev_signal:
                # New signal — emit
                bar = df.iloc[-1]
                signal_time = df.index[-1]
                if hasattr(signal_time, "to_pydatetime"):
                    signal_time = signal_time.to_pydatetime()

                signal_dict = {
                    "signal_time":   signal_time.isoformat() if hasattr(signal_time, "isoformat") else str(signal_time),
                    "ticker":        ticker,
                    "strategy_slug": slug,
                    "interval":      "1MIN",
                    "signal_type":   latest_signal,
                    "close_price":   float(bar.get("Close", 0)),
                    "bar_open":      float(bar.get("Open", 0)),
                    "bar_high":      float(bar.get("High", 0)),
                    "bar_low":       float(bar.get("Low", 0)),
                    "bar_volume":    int(bar.get("Volume", 0)),
                }

                with self._lock:
                    self._last_signals.setdefault(ticker, {})[slug] = latest_signal
                    self._signal_count += 1
                    # Append to persistent log (keep last 500)
                    self._signal_log.append(signal_dict)
                    if len(self._signal_log) > 500:
                        self._signal_log = self._signal_log[-500:]

                # Persist to DB
                self._persist_signal(signal_dict)

                logger.info(
                    "[IntradayMonitor] Signal: %s %s %s @ %.2f",
                    "BUY" if latest_signal == 1 else "SELL",
                    ticker, slug, signal_dict["close_price"],
                )

            # Always update last_signals
            with self._lock:
                self._last_signals.setdefault(ticker, {})[slug] = latest_signal

    def _load_intraday_strategies(self) -> list[Any]:
        """Load strategy modules tagged with "1MIN" in their INTERVALS attribute."""
        try:
            from frontend.strategy.engine import list_strategies, load_strategy
        except Exception as exc:
            logger.warning("[IntradayMonitor] Could not import strategy engine: %s", exc)
            return []

        all_strats = list_strategies()
        modules: list[Any] = []

        for s in all_strats:
            if self._strategy_slugs and s["name"] not in self._strategy_slugs:
                continue
            try:
                mod = load_strategy(s["name"], is_builtin=s["is_builtin"])
                intervals = getattr(mod, "INTERVALS", ["1D"])
                if "1MIN" in intervals:
                    modules.append(mod)
            except Exception as exc:
                logger.debug("[IntradayMonitor] Could not load strategy %s: %s", s["name"], exc)

        return modules

    def _persist_signal(self, sig: dict) -> None:
        """Write the signal to the intraday_signals DB table."""
        try:
            from src.scanner.models import IntradaySignal
            from src.database import SessionLocal

            db = SessionLocal()
            try:
                row = IntradaySignal(
                    signal_time   = _parse_dt(sig["signal_time"]),
                    ticker        = sig["ticker"],
                    strategy_slug = sig["strategy_slug"],
                    interval      = sig["interval"],
                    signal_type   = sig["signal_type"],
                    close_price   = sig.get("close_price"),
                    bar_open      = sig.get("bar_open"),
                    bar_high      = sig.get("bar_high"),
                    bar_low       = sig.get("bar_low"),
                    bar_volume    = sig.get("bar_volume"),
                )
                db.add(row)
                db.commit()
            finally:
                db.close()
        except Exception as exc:
            logger.warning("[IntradayMonitor] DB persist failed: %s", exc)


# ---------------------------------------------------------------------------
# Process-singleton
# ---------------------------------------------------------------------------

_monitor_instance: Optional[IntradayMonitor] = None
_monitor_lock = threading.Lock()


def get_monitor() -> IntradayMonitor:
    """Return (and lazily create) the process-level singleton IntradayMonitor."""
    global _monitor_instance
    with _monitor_lock:
        if _monitor_instance is None:
            _monitor_instance = IntradayMonitor()
        return _monitor_instance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_dt(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _append_new_bars(
    existing: Optional[pd.DataFrame],
    new: pd.DataFrame,
) -> pd.DataFrame:
    """Append *new* bars to *existing*, deduplicating by timestamp index."""
    if existing is None or existing.empty:
        return new
    combined = pd.concat([existing, new])
    combined = combined[~combined.index.duplicated(keep="last")]
    return combined.sort_index()
