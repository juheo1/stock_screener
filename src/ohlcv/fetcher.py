"""
src.ohlcv.fetcher
=================
Incremental OHLCV fetcher: compares what the store holds vs what yfinance
can provide, downloads only the delta, and appends.

Public API
----------
OHLCVFetcher    High-level sync interface used by the scanner and scheduler.
SyncReport      Result summary returned by sync methods.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from src.ohlcv.store import OHLCVStore

logger = logging.getLogger(__name__)

# Gap threshold: if last bar is older than this many calendar days,
# do a full 2-year refresh instead of an incremental delta.
_FULL_REFRESH_DAYS = 5

# yfinance fetch constants
_DAILY_FULL_PERIOD   = "2y"
_DAILY_DELTA_PERIOD  = "5d"
_INTRADAY_1M_PERIOD  = "7d"
_INTRADAY_5M_PERIOD  = "60d"
_INTRADAY_PERIODS    = {"1min": _INTRADAY_1M_PERIOD, "5min": _INTRADAY_5M_PERIOD}
_INTRADAY_YF_IVLS    = {"1min": "1m", "5min": "5m"}

# Batch download chunk size
_CHUNK_SIZE = 100


@dataclass
class SyncReport:
    """Summary of a sync operation."""

    succeeded: list[str] = field(default_factory=list)
    skipped:   list[str] = field(default_factory=list)
    failed:    list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.succeeded) + len(self.skipped) + len(self.failed)


class OHLCVFetcher:
    """Download daily and intraday OHLCV bars from yfinance into an OHLCVStore.

    Parameters
    ----------
    store:
        The :class:`OHLCVStore` to read from and write to.
    stale_hours:
        Re-fetch daily data if the last sync was more than this many hours ago
        (default: 18 — covers overnight gap without double-fetching intraday).
    """

    def __init__(self, store: OHLCVStore, stale_hours: int = 18) -> None:
        self.store       = store
        self.stale_hours = stale_hours

    # ------------------------------------------------------------------
    # Daily sync
    # ------------------------------------------------------------------

    def sync_daily(
        self,
        tickers: list[str],
        force_full: bool = False,
    ) -> SyncReport:
        """Ensure the store has up-to-date daily OHLCV data for all *tickers*.

        For each ticker:
        - If no data or last bar is old (> _FULL_REFRESH_DAYS): full 2y fetch.
        - If last bar is recent: incremental 5-day fetch.
        - If last sync was within stale_hours: skip entirely.

        Parameters
        ----------
        tickers:
            List of ticker symbols.
        force_full:
            When True, always fetch the full 2-year history (ignores cache age).

        Returns
        -------
        SyncReport
        """
        report = SyncReport()
        today  = date.today()

        # Partition into full-refresh vs incremental
        full_refresh: list[str] = []
        incremental:  list[str] = []
        skip:         list[str] = []

        for ticker in tickers:
            if force_full:
                full_refresh.append(ticker)
                continue

            last_sync = self.store.get_last_updated(ticker, "daily")
            if last_sync is not None:
                age_hours = (datetime.utcnow() - last_sync).total_seconds() / 3600
                if age_hours < self.stale_hours:
                    skip.append(ticker)
                    continue

            last_bar = self.store.last_bar_date(ticker)
            if last_bar is None or (today - last_bar).days > _FULL_REFRESH_DAYS:
                full_refresh.append(ticker)
            else:
                incremental.append(ticker)

        report.skipped.extend(skip)
        logger.info(
            "[OHLCVFetcher] daily sync: %d full-refresh, %d incremental, %d skip",
            len(full_refresh), len(incremental), len(skip),
        )

        # Full refresh batches
        if full_refresh:
            delta = self._batch_download_daily(full_refresh, period=_DAILY_FULL_PERIOD)
            for ticker in full_refresh:
                df = delta.get(ticker)
                if df is not None and not df.empty:
                    self.store.write_daily(ticker, df)
                    report.succeeded.append(ticker)
                else:
                    report.failed.append(ticker)

        # Incremental batches
        if incremental:
            delta = self._batch_download_daily(incremental, period=_DAILY_DELTA_PERIOD)
            for ticker in incremental:
                new_df = delta.get(ticker)
                if new_df is None or new_df.empty:
                    report.failed.append(ticker)
                    continue
                existing = self.store.read_daily(ticker)
                merged = _merge_ohlcv(existing, new_df)
                self.store.write_daily(ticker, merged)
                report.succeeded.append(ticker)

        return report

    # ------------------------------------------------------------------
    # Intraday archive sync (nightly)
    # ------------------------------------------------------------------

    def sync_intraday(
        self,
        tickers: list[str],
        intervals: list[str] | None = None,
        force_full: bool = False,
    ) -> SyncReport:
        """Archive intraday bars for completed trading days.

        For each ticker × interval:
        - Fetch the maximum available window from yfinance.
        - For each day in the window that is not yet archived, write a file.

        Parameters
        ----------
        tickers:
            List of ticker symbols.
        intervals:
            Intraday interval identifiers to archive (e.g. ``["1min", "5min"]``).
            Defaults to all intervals in ``_INTRADAY_PERIODS``.
        force_full:
            When True, overwrite already-archived days.
        """
        if intervals is None:
            intervals = list(_INTRADAY_PERIODS.keys())

        report = SyncReport()

        for interval in intervals:
            period = _INTRADAY_PERIODS.get(interval)
            yf_ivl = _INTRADAY_YF_IVLS.get(interval)
            if period is None or yf_ivl is None:
                logger.warning("[OHLCVFetcher] Unknown intraday interval: %s", interval)
                continue

            for chunk_tickers in _chunked(tickers, _CHUNK_SIZE):
                raw = _yf_download_batch(chunk_tickers, period=period, interval=yf_ivl)
                for ticker in chunk_tickers:
                    df = _extract_ticker_slice(raw, ticker)
                    if df is None or df.empty:
                        report.failed.append(ticker)
                        continue

                    archived_any = False
                    for day, day_df in _split_by_day(df):
                        if day == date.today():
                            # Today is incomplete — skip; handled by live tier
                            continue
                        if not force_full and self.store.has_intraday(ticker, interval, day):
                            continue
                        self.store.write_intraday(ticker, interval, day, day_df)
                        archived_any = True

                    if archived_any:
                        report.succeeded.append(ticker)
                    else:
                        report.skipped.append(ticker)

        return report

    # ------------------------------------------------------------------
    # Live bar fetch (intraday monitor)
    # ------------------------------------------------------------------

    def fetch_live_bars(
        self,
        tickers: list[str],
        since: Optional[datetime] = None,
    ) -> dict[str, pd.DataFrame]:
        """Fetch today's 1-minute bars for all *tickers*.

        Parameters
        ----------
        tickers:
            Watchlist tickers.
        since:
            If provided, return only bars with a timestamp newer than this.

        Returns
        -------
        Dict of ticker → DataFrame (may be empty if no new bars).
        """
        result: dict[str, pd.DataFrame] = {}
        raw = _yf_download_batch(tickers, period="1d", interval="1m")

        for ticker in tickers:
            df = _extract_ticker_slice(raw, ticker)
            if df is None or df.empty:
                result[ticker] = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
                continue
            if since is not None:
                # Filter to bars newer than `since` (timezone-aware comparison)
                since_ts = pd.Timestamp(since, tz="UTC") if since.tzinfo is None else pd.Timestamp(since)
                idx = df.index
                if idx.tzinfo is None:
                    idx = idx.tz_localize("UTC")
                    df = df.set_index(idx)
                df = df[df.index > since_ts]
            result[ticker] = df

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _batch_download_daily(
        self, tickers: list[str], period: str
    ) -> dict[str, Optional[pd.DataFrame]]:
        """Download daily bars for all *tickers* in chunks."""
        results: dict[str, Optional[pd.DataFrame]] = {}
        for chunk in _chunked(tickers, _CHUNK_SIZE):
            raw = _yf_download_batch(chunk, period=period, interval="1d")
            for ticker in chunk:
                results[ticker] = _extract_ticker_slice(raw, ticker)
        return results


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _yf_download_batch(
    tickers: list[str], period: str, interval: str = "1d"
) -> pd.DataFrame:
    """Single yf.download call for a chunk of tickers."""
    import yfinance as yf

    if not tickers:
        return pd.DataFrame()
    try:
        return yf.download(
            tickers,
            period=period,
            interval=interval,
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as exc:
        logger.warning("[OHLCVFetcher] yf.download failed: %s", exc)
        return pd.DataFrame()


def _extract_ticker_slice(
    raw: pd.DataFrame, ticker: str
) -> Optional[pd.DataFrame]:
    """Extract and clean the OHLCV slice for a single *ticker* from a batch download."""
    if raw is None or raw.empty:
        return None
    try:
        if isinstance(raw.columns, pd.MultiIndex):
            df = raw.xs(ticker, axis=1, level=1)
        else:
            df = raw.copy()
    except KeyError:
        return None

    if df is None or df.empty:
        return None

    cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    if not cols:
        return None
    df = df[cols].dropna()
    return df if not df.empty else None


def _merge_ohlcv(
    existing: Optional[pd.DataFrame], new: pd.DataFrame
) -> pd.DataFrame:
    """Merge *new* bars into *existing*, deduplicating by index (keep new)."""
    if existing is None or existing.empty:
        return new
    combined = pd.concat([existing, new])
    combined = combined[~combined.index.duplicated(keep="last")]
    return combined.sort_index()


def _split_by_day(df: pd.DataFrame):
    """Yield (date, sub_df) pairs by calendar day."""
    idx = df.index
    if hasattr(idx, "date"):
        dates = idx.date
    else:
        dates = pd.DatetimeIndex(idx).date
    for d in sorted(set(dates)):
        mask = dates == d
        yield d, df.iloc[mask]


def _chunked(lst: list, size: int):
    """Yield successive *size*-length chunks from *lst*."""
    for i in range(0, len(lst), size):
        yield lst[i:i + size]
