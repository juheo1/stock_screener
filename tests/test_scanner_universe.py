"""
tests/test_scanner_universe.py
===============================
Unit tests for :mod:`src.scanner.universe`.

These tests mock the underlying ETF holdings fetch so they run offline
without touching yfinance or the database.

Run with::

    pytest tests/test_scanner_universe.py -v
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.scanner.universe import (
    DEFAULT_SCANNER_ETFS,
    UniverseSnapshot,
    load_cached_universe,
    resolve_universe,
    save_universe_cache,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_snapshot(etfs=None, tickers=None) -> UniverseSnapshot:
    etfs = etfs or ["SPY", "QQQ"]
    tickers = tickers or ["AAPL", "MSFT", "SPY", "QQQ"]
    return UniverseSnapshot(
        tickers=sorted(tickers),
        ticker_to_etfs={t: [etfs[0]] for t in tickers},
        source_etfs=etfs,
    )


# ---------------------------------------------------------------------------
# UniverseSnapshot
# ---------------------------------------------------------------------------

class TestUniverseSnapshot:
    def test_to_dict_round_trips(self):
        snap = _make_snapshot()
        d = snap.to_dict()
        snap2 = UniverseSnapshot.from_dict(d)
        assert snap2.tickers == snap.tickers
        assert snap2.source_etfs == snap.source_etfs
        assert snap2.ticker_to_etfs == snap.ticker_to_etfs

    def test_resolved_at_is_set_automatically(self):
        snap = _make_snapshot()
        assert snap.resolved_at != ""
        # Should be parseable as an ISO datetime
        dt = datetime.fromisoformat(snap.resolved_at)
        assert dt is not None

    def test_from_dict_missing_resolved_at(self):
        d = {
            "tickers": ["AAPL"],
            "ticker_to_etfs": {"AAPL": ["SPY"]},
            "source_etfs": ["SPY"],
        }
        snap = UniverseSnapshot.from_dict(d)
        assert snap.resolved_at == ""


# ---------------------------------------------------------------------------
# save_universe_cache / load_cached_universe
# ---------------------------------------------------------------------------

class TestCacheIO:
    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.scanner.universe._CACHE_FILE", tmp_path / "cache.json")

        snap = _make_snapshot()
        save_universe_cache(snap)
        loaded = load_cached_universe(snap.source_etfs)

        assert loaded is not None
        assert loaded.tickers == snap.tickers
        assert loaded.source_etfs == snap.source_etfs

    def test_load_returns_none_when_no_cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.scanner.universe._CACHE_FILE", tmp_path / "nonexistent.json")
        result = load_cached_universe()
        assert result is None

    def test_load_returns_none_when_cache_expired(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.scanner.universe._CACHE_FILE", tmp_path / "cache.json")

        old_time = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        snap = _make_snapshot()
        d = snap.to_dict()
        d["resolved_at"] = old_time
        (tmp_path / "cache.json").write_text(json.dumps(d), encoding="utf-8")

        result = load_cached_universe(snap.source_etfs)
        assert result is None

    def test_load_returns_none_on_etf_set_mismatch(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.scanner.universe._CACHE_FILE", tmp_path / "cache.json")
        snap = _make_snapshot(etfs=["SPY", "QQQ"])
        save_universe_cache(snap)

        result = load_cached_universe(["SPY", "IWM"])  # different ETF set
        assert result is None

    def test_load_returns_cache_when_etfs_match(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.scanner.universe._CACHE_FILE", tmp_path / "cache.json")
        snap = _make_snapshot(etfs=["SPY", "QQQ"])
        save_universe_cache(snap)

        loaded = load_cached_universe(["QQQ", "SPY"])  # order-independent
        assert loaded is not None
        assert sorted(loaded.source_etfs) == ["QQQ", "SPY"]

    def test_save_handles_write_error_gracefully(self, tmp_path, monkeypatch):
        # Point cache file to a read-only path (simulate write failure)
        monkeypatch.setattr("src.scanner.universe._CACHE_FILE", Path("/nonexistent_dir/cache.json"))
        snap = _make_snapshot()
        # Should not raise
        save_universe_cache(snap)


# ---------------------------------------------------------------------------
# resolve_universe
# ---------------------------------------------------------------------------

class TestResolveUniverse:
    @patch("src.scanner.universe._fetch_holdings")
    def test_includes_etf_itself(self, mock_fetch, tmp_path, monkeypatch):
        monkeypatch.setattr("src.scanner.universe._CACHE_FILE", tmp_path / "cache.json")
        mock_fetch.return_value = ["AAPL", "MSFT"]

        snap = resolve_universe(["SPY"], use_cache=False)
        assert "SPY" in snap.tickers

    @patch("src.scanner.universe._fetch_holdings")
    def test_deduplicates_tickers_across_etfs(self, mock_fetch, tmp_path, monkeypatch):
        monkeypatch.setattr("src.scanner.universe._CACHE_FILE", tmp_path / "cache.json")
        # Both ETFs hold AAPL
        mock_fetch.return_value = ["AAPL", "MSFT"]

        snap = resolve_universe(["SPY", "QQQ"], use_cache=False)
        assert snap.tickers.count("AAPL") == 1

    @patch("src.scanner.universe._fetch_holdings")
    def test_ticker_to_etfs_lists_all_source_etfs(self, mock_fetch, tmp_path, monkeypatch):
        monkeypatch.setattr("src.scanner.universe._CACHE_FILE", tmp_path / "cache.json")
        mock_fetch.return_value = ["AAPL"]

        snap = resolve_universe(["SPY", "QQQ"], use_cache=False)
        # AAPL is in both ETFs
        assert "SPY" in snap.ticker_to_etfs["AAPL"]
        assert "QQQ" in snap.ticker_to_etfs["AAPL"]

    @patch("src.scanner.universe._fetch_holdings")
    def test_tickers_sorted(self, mock_fetch, tmp_path, monkeypatch):
        monkeypatch.setattr("src.scanner.universe._CACHE_FILE", tmp_path / "cache.json")
        mock_fetch.return_value = ["MSFT", "AAPL", "GOOG"]

        snap = resolve_universe(["SPY"], use_cache=False)
        assert snap.tickers == sorted(snap.tickers)

    @patch("src.scanner.universe._fetch_holdings")
    def test_uses_default_etfs_when_none_provided(self, mock_fetch, tmp_path, monkeypatch):
        monkeypatch.setattr("src.scanner.universe._CACHE_FILE", tmp_path / "cache.json")
        mock_fetch.return_value = []

        snap = resolve_universe(None, use_cache=False)
        assert snap.source_etfs == DEFAULT_SCANNER_ETFS

    @patch("src.scanner.universe._fetch_holdings")
    def test_holdings_fetch_failure_still_includes_etf(self, mock_fetch, tmp_path, monkeypatch):
        monkeypatch.setattr("src.scanner.universe._CACHE_FILE", tmp_path / "cache.json")
        mock_fetch.side_effect = RuntimeError("API error")

        snap = resolve_universe(["SPY"], use_cache=False)
        assert "SPY" in snap.tickers  # ETF itself should still be there

    @patch("src.scanner.universe._fetch_holdings")
    def test_uses_cache_when_valid(self, mock_fetch, tmp_path, monkeypatch):
        monkeypatch.setattr("src.scanner.universe._CACHE_FILE", tmp_path / "cache.json")
        snap = _make_snapshot(etfs=["SPY"])
        save_universe_cache(snap)

        result = resolve_universe(["SPY"], use_cache=True)
        mock_fetch.assert_not_called()
        assert result.tickers == snap.tickers

    @patch("src.scanner.universe._fetch_holdings")
    def test_saves_to_cache_after_resolve(self, mock_fetch, tmp_path, monkeypatch):
        cache_file = tmp_path / "cache.json"
        monkeypatch.setattr("src.scanner.universe._CACHE_FILE", cache_file)
        mock_fetch.return_value = ["AAPL"]

        resolve_universe(["SPY"], use_cache=False)
        assert cache_file.exists()
