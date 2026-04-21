"""
src.database
============
Database engine, session factory, and schema initialisation.

The default backend is SQLite (local file).  Set ``DATABASE_URL`` in .env to
switch to PostgreSQL for multi-user / concurrent use.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

from src.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base class for all ORM models
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    """Declarative base used by every ORM model in :mod:`src.models`."""
    pass


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def _build_engine():
    """Create a SQLAlchemy engine from settings.

    For SQLite, the database file is created automatically if it does not
    exist.  WAL mode is enabled to allow concurrent reads while a write is
    in progress (important when the scheduler writes while the API reads).

    Returns
    -------
    sqlalchemy.engine.Engine
    """
    url = settings.database_url

    # Ensure the parent directory exists for SQLite paths
    if url.startswith("sqlite:///"):
        db_path = Path(url.replace("sqlite:///", ""))
        db_path.parent.mkdir(parents=True, exist_ok=True)

    connect_args = {}
    if "sqlite" in url:
        connect_args["check_same_thread"] = False

    engine = create_engine(
        url,
        connect_args=connect_args,
        echo=False,
    )

    # Enable WAL journal mode for SQLite
    if "sqlite" in url:
        @event.listens_for(engine, "connect")
        def set_wal(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA journal_mode=WAL")
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
            # Allow up to 15 s of waiting when another thread holds the write lock
            # instead of raising "database is locked" immediately.
            dbapi_conn.execute("PRAGMA busy_timeout=15000")

    logger.info("Database engine created: %s", url)
    return engine


engine = _build_engine()

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_db() -> Session:
    """Yield a database session, closing it when the caller is done.

    Intended for use as a FastAPI dependency::

        @router.get("/example")
        def example(db: Session = Depends(get_db)):
            ...

    Yields
    ------
    sqlalchemy.orm.Session
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables if they do not already exist, then run column migrations.

    Safe to call multiple times.  New columns added to existing ORM models are
    applied via ``ALTER TABLE … ADD COLUMN`` so that existing SQLite databases
    are upgraded automatically without losing data.
    """
    # Import models so that SQLAlchemy registers them with Base.metadata
    import src.models                # noqa: F401
    import src.scanner.models        # noqa: F401  (scanner tables)
    import src.trade_tracker.models  # noqa: F401  (trade tracking table)

    Base.metadata.create_all(bind=engine)
    _migrate_columns()
    logger.info("Database initialised.")


# Columns added after the initial schema; applied to existing databases on startup.
_NEW_COLUMNS: list[tuple[str, str, str]] = [
    # (table, column, sqlite_type)
    ("statements_balance",  "current_assets",              "REAL"),
    ("statements_balance",  "current_liabilities",         "REAL"),
    ("statements_cashflow", "depreciation_amortization",   "REAL"),
    ("metrics_quarterly",   "current_ratio",               "REAL"),
    ("metrics_quarterly",   "pb_ratio",                    "REAL"),
    ("metrics_quarterly",   "graham_number",               "REAL"),
    ("metrics_quarterly",   "ncav_per_share",              "REAL"),
    ("metrics_quarterly",   "roe",                         "REAL"),
    ("metrics_quarterly",   "owner_earnings_per_share",    "REAL"),
    ("metrics_quarterly",   "quality_score",               "REAL"),
    ("metals_series",       "inventory_oz",                "REAL"),
    ("equities",            "description",                 "TEXT"),
    ("scan_backtests",  "spy_return_pct",       "REAL"),
    ("scan_backtests",  "strategy_return_pct",  "REAL"),
    ("scan_backtests",  "beat_spy",             "INTEGER"),
    ("scan_backtests",  "avg_return_pct",       "REAL"),
]


def _migrate_columns() -> None:
    """Add any missing columns to existing tables (idempotent)."""
    with engine.connect() as conn:
        for table, column, col_type in _NEW_COLUMNS:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                conn.commit()
                logger.info("Migration: added %s.%s", table, column)
            except Exception:
                pass  # Column already exists — safe to ignore
