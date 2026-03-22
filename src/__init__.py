"""
src - Stock Screener backend package.

Submodules:
    database    -- SQLAlchemy engine, session factory, and Base.
    models      -- ORM table definitions.
    ingestion   -- Data-fetching adapters (equity, macro, metals).
    metrics     -- Derived metric computation (gross margin, ROIC, etc.).
    zombie      -- Zombie-company classification logic.
    retirement  -- Monte Carlo retirement projection engine.
    scheduler   -- APScheduler job definitions.
"""
