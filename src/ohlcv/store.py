"""
src.ohlcv.store
===============
Parquet-based OHLCV storage layer.

Directory layout::

    data/ohlcv/
      daily/
        AAPL.parquet        # max available 1D bars
        MSFT.parquet
      intraday/
        1min/AAPL/2026-04-21.parquet
        5min/AAPL/2026-04-21.parquet
      live/
        AAPL.parquet        # today's accumulating 1m bars
      meta.json             # last-updated timestamps per ticker per interval

All writes use an atomic temp-file + rename pattern to prevent corruption.

Public API
----------
OHLCVStore      Storage facade with read/write methods for all three tiers.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

_OHLCV_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


class OHLCVStore:
    """Read/write OHLCV Parquet files for daily, intraday archive, and live tiers.

    Parameters
    ----------
    root_dir:
        Root directory for all OHLCV storage (e.g. ``data/ohlcv``).
    """

    def __init__(self, root_dir: str | Path) -> None:
        self.root = Path(root_dir)
        self._daily_dir    = self.root / "daily"
        self._intraday_dir = self.root / "intraday"
        self._live_dir     = self.root / "live"
        self._meta_path    = self.root / "meta.json"

        for d in (self._daily_dir, self._live_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_parquet(self, path: Path) -> Optional[pd.DataFrame]:
        """Read a Parquet file; return None on any error."""
        if not path.exists():
            return None
        try:
            df = pd.read_parquet(path)
            return df if not df.empty else None
        except Exception as exc:
            logger.warning("[OHLCVStore] Failed to read %s: %s", path, exc)
            return None

    def _write_parquet(self, path: Path, df: pd.DataFrame) -> None:
        """Write *df* to *path* atomically (temp file + rename)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        os.close(fd)
        try:
            df.to_parquet(tmp, engine="pyarrow", compression="snappy")
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # Meta / timestamps
    # ------------------------------------------------------------------

    def _load_meta(self) -> dict:
        if not self._meta_path.exists():
            return {}
        try:
            return json.loads(self._meta_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_meta(self, meta: dict) -> None:
        fd, tmp = tempfile.mkstemp(dir=self.root, suffix=".tmp")
        os.close(fd)
        try:
            Path(tmp).write_text(json.dumps(meta, indent=2), encoding="utf-8")
            os.replace(tmp, self._meta_path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _set_last_updated(self, ticker: str, interval: str) -> None:
        meta = self._load_meta()
        meta.setdefault(ticker, {})[interval] = datetime.utcnow().isoformat()
        self._save_meta(meta)

    def get_last_updated(self, ticker: str, interval: str) -> Optional[datetime]:
        """Return the UTC datetime when *ticker*/*interval* was last synced."""
        meta = self._load_meta()
        ts = meta.get(ticker, {}).get(interval)
        if ts is None:
            return None
        try:
            return datetime.fromisoformat(ts)
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # Daily tier
    # ------------------------------------------------------------------

    def _daily_path(self, ticker: str) -> Path:
        return self._daily_dir / f"{ticker.upper()}.parquet"

    def read_daily(self, ticker: str) -> Optional[pd.DataFrame]:
        """Return the stored daily DataFrame for *ticker*, or None."""
        return self._read_parquet(self._daily_path(ticker))

    def write_daily(self, ticker: str, df: pd.DataFrame) -> None:
        """Persist *df* as the daily cache for *ticker*."""
        cols = [c for c in _OHLCV_COLUMNS if c in df.columns]
        self._write_parquet(self._daily_path(ticker), df[cols])
        self._set_last_updated(ticker, "daily")

    def last_bar_date(self, ticker: str, interval: str = "daily") -> Optional[date]:
        """Return the date of the most recent bar in the stored daily file."""
        if interval == "daily":
            df = self.read_daily(ticker)
        else:
            return None
        if df is None or df.empty:
            return None
        idx = df.index[-1]
        if hasattr(idx, "date"):
            return idx.date()
        try:
            return pd.Timestamp(idx).date()
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Intraday archive tier (completed days)
    # ------------------------------------------------------------------

    def _intraday_path(self, ticker: str, interval: str, day: date) -> Path:
        return (
            self._intraday_dir
            / interval
            / ticker.upper()
            / f"{day.isoformat()}.parquet"
        )

    def read_intraday(
        self, ticker: str, interval: str, day: date
    ) -> Optional[pd.DataFrame]:
        """Return archived intraday bars for *ticker*/*interval* on *day*."""
        return self._read_parquet(self._intraday_path(ticker, interval, day))

    def read_intraday_range(
        self,
        ticker: str,
        interval: str,
        start: date,
        end: date,
    ) -> Optional[pd.DataFrame]:
        """Concatenate archived intraday files for *ticker* over [start, end]."""
        ticker_dir = self._intraday_dir / interval / ticker.upper()
        if not ticker_dir.exists():
            return None

        frames: list[pd.DataFrame] = []
        current = start
        while current <= end:
            path = ticker_dir / f"{current.isoformat()}.parquet"
            df = self._read_parquet(path)
            if df is not None:
                frames.append(df)
            current = _next_day(current)

        if not frames:
            return None
        combined = pd.concat(frames).sort_index()
        return combined if not combined.empty else None

    def write_intraday(
        self, ticker: str, interval: str, day: date, df: pd.DataFrame
    ) -> None:
        """Persist intraday bars for *ticker*/*interval* on *day*."""
        cols = [c for c in _OHLCV_COLUMNS if c in df.columns]
        self._write_parquet(self._intraday_path(ticker, interval, day), df[cols])
        self._set_last_updated(ticker, interval)

    def has_intraday(self, ticker: str, interval: str, day: date) -> bool:
        """Return True if an archived file exists for *ticker*/*interval*/*day*."""
        return self._intraday_path(ticker, interval, day).exists()

    # ------------------------------------------------------------------
    # Live tier (today's in-progress bars)
    # ------------------------------------------------------------------

    def _live_path(self, ticker: str) -> Path:
        return self._live_dir / f"{ticker.upper()}.parquet"

    def read_live(self, ticker: str) -> Optional[pd.DataFrame]:
        """Return today's live (in-memory checkpoint) bars for *ticker*."""
        return self._read_parquet(self._live_path(ticker))

    def write_live(self, ticker: str, df: pd.DataFrame) -> None:
        """Overwrite the live checkpoint for *ticker* with *df*."""
        cols = [c for c in _OHLCV_COLUMNS if c in df.columns]
        self._write_parquet(self._live_path(ticker), df[cols])

    def finalize_live(self, ticker: str, day: date) -> None:
        """Move the live file to the intraday archive for *day*."""
        df = self.read_live(ticker)
        if df is not None and not df.empty:
            self.write_intraday(ticker, "1min", day, df)
            logger.info("[OHLCVStore] Finalized live → intraday/1min/%s/%s", ticker, day)
        live_path = self._live_path(ticker)
        if live_path.exists():
            live_path.unlink()

    # ------------------------------------------------------------------
    # Housekeeping
    # ------------------------------------------------------------------

    def list_tickers(self, interval: str = "daily") -> list[str]:
        """Return a list of tickers that have cached data for *interval*."""
        if interval == "daily":
            return [p.stem for p in self._daily_dir.glob("*.parquet")]
        # intraday: list subdirectories under data/ohlcv/intraday/<interval>/
        interval_dir = self._intraday_dir / interval
        if not interval_dir.exists():
            return []
        return [p.name for p in interval_dir.iterdir() if p.is_dir()]

    def delete_ticker(self, ticker: str) -> None:
        """Remove all cached files for *ticker* across all tiers."""
        ticker = ticker.upper()
        # daily
        p = self._daily_path(ticker)
        if p.exists():
            p.unlink()
        # live
        p = self._live_path(ticker)
        if p.exists():
            p.unlink()
        # intraday
        for interval_dir in self._intraday_dir.iterdir():
            if not interval_dir.is_dir():
                continue
            ticker_dir = interval_dir / ticker
            if ticker_dir.exists():
                import shutil
                shutil.rmtree(ticker_dir, ignore_errors=True)
        # meta
        meta = self._load_meta()
        if ticker in meta:
            del meta[ticker]
            self._save_meta(meta)

    def retention_cleanup(self, interval: str, max_age_days: int) -> int:
        """Delete intraday archive files older than *max_age_days*.

        Returns
        -------
        Number of files deleted.
        """
        from datetime import timedelta
        cutoff = date.today() - timedelta(days=max_age_days)
        interval_dir = self._intraday_dir / interval
        if not interval_dir.exists():
            return 0

        deleted = 0
        for ticker_dir in interval_dir.iterdir():
            if not ticker_dir.is_dir():
                continue
            for parquet_file in ticker_dir.glob("*.parquet"):
                try:
                    file_date = date.fromisoformat(parquet_file.stem)
                except ValueError:
                    continue
                if file_date < cutoff:
                    parquet_file.unlink()
                    deleted += 1

        logger.info(
            "[OHLCVStore] Retention cleanup (%s, >%dd): deleted %d files.",
            interval, max_age_days, deleted,
        )
        return deleted


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _next_day(d: date) -> date:
    from datetime import timedelta
    return d + timedelta(days=1)
