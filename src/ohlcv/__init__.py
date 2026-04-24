"""
src.ohlcv
=========
OHLCV cache layer: Parquet-based local storage for daily and intraday bars.

Modules
-------
store       Read/write Parquet files (pure I/O).
fetcher     Incremental sync from yfinance to the store.
scheduler   Background jobs: nightly sync, retention cleanup.
"""
