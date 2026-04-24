"""
src.config
==========
Application settings loaded from the environment / .env file.
"""

from __future__ import annotations

import secrets
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Anchor all relative paths to the project root (parent of src/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _default_db_url() -> str:
    """Return an absolute SQLite URL anchored to the project root."""
    db_path = _PROJECT_ROOT / "data" / "stock_screener.db"
    return f"sqlite:///{db_path}"


class Settings(BaseSettings):
    """All configurable knobs for the stock screener application.

    Values are read from environment variables or from a ``.env`` file in
    the working directory.  See ``.env.example`` for descriptions.

    Attributes
    ----------
    fred_api_key : str
        Free API key from https://fred.stlouisfed.org.
    database_url : str
        SQLAlchemy connection string (SQLite by default).
    api_host : str
        Host for the FastAPI server.
    api_port : int
        Port for the FastAPI server.
    dash_host : str
        Host for the Dash frontend server.
    dash_port : int
        Port for the Dash frontend server.
    dash_debug : bool
        Enable Dash debug mode (hot-reload etc.).
    secret_key : str
        Random secret used to sign JWT tokens.
    algorithm : str
        JWT signing algorithm (default HS256).
    access_token_expire_minutes : int
        Token lifetime in minutes.
    scheduler_hour : int
        Hour (0-23) for the daily data refresh job.
    scheduler_minute : int
        Minute (0-59) for the daily data refresh job.
    scanner_hour : int
        UTC hour for the daily strategy scanner (default 21 = 5 PM ET).
    scanner_minute : int
        UTC minute for the daily strategy scanner.
    scanner_history_days : int
        Number of past trading days included in scanner results (default 10).
    scanner_etfs : str
        Comma-separated list of ETF tickers for the scanner universe.
        Empty string uses the built-in default list.
    log_level : str
        Python logging level string (DEBUG, INFO, WARNING, ERROR).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    fred_api_key: str = ""
    newsapi_key: str = ""
    finnhub_api_key: str = ""
    alphavantage_api_key: str = ""
    database_url: str = Field(default_factory=_default_db_url)

    # Feature flags (Part 8)
    enable_news_feed: bool = True
    enable_gdelt: bool = False
    enable_sentiment: bool = True
    enable_earthquake: bool = True

    api_host: str = "127.0.0.1"
    api_port: int = 8000

    dash_host: str = "127.0.0.1"
    dash_port: int = 8050
    dash_debug: bool = False

    secret_key: str = Field(default_factory=lambda: secrets.token_hex(32))
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080  # 7 days

    # Admin API key — required for admin/destructive endpoints in production.
    # In dev mode (DEV_MODE=true), admin endpoints are open without a key.
    admin_api_key: str = ""

    # Dev mode — enables open access to all endpoints (no API key needed).
    # MUST be false in any network-exposed deployment.
    dev_mode: bool = True

    scheduler_hour: int = 6
    scheduler_minute: int = 30

    # Daily strategy scanner settings
    scanner_hour: int = 21          # UTC hour for end-of-day scan (21:00 = 5 PM ET)
    scanner_minute: int = 30        # UTC minute for end-of-day scan
    scanner_history_days: int = 10  # Number of past trading days to include in results
    scanner_etfs: str = ""          # Comma-separated ETF list; empty = use default

    log_level: str = "INFO"

    # ---------------------------------------------------------------------------
    # OHLCV cache layer
    # ---------------------------------------------------------------------------

    # Root directory for Parquet OHLCV files
    ohlcv_dir: str = "data/ohlcv"

    # Re-fetch daily bars if last sync was more than this many hours ago
    ohlcv_daily_stale_hours: int = 18

    # Comma-separated intraday intervals to archive nightly (e.g. "1min,5min")
    ohlcv_intraday_intervals: str = "1min,5min"

    # How many days to retain archived intraday files (default: 1 year)
    ohlcv_intraday_retention_days: int = 365

    # Whether to run the nightly OHLCV sync job automatically
    ohlcv_sync_after_market_close: bool = True

    # ---------------------------------------------------------------------------
    # Intraday monitor
    # ---------------------------------------------------------------------------

    # Seconds between live bar polls
    intraday_poll_interval: int = 60

    # Watchlist source: "manual" | "auto" | "both"
    intraday_watchlist_mode: str = "manual"

    # Maximum number of tickers in the intraday watchlist
    intraday_watchlist_max: int = 50

    # Auto-mode: include tickers with signals within the last N days
    intraday_auto_signal_window: int = 1

    # How many days to keep intraday signals in the DB
    intraday_signal_retention_days: int = 7


settings = Settings()
