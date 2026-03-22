"""
src.api.deps
============
Shared FastAPI dependency functions.

Provides
--------
get_db   -- Yield a SQLAlchemy session (one per request).
"""

from __future__ import annotations

from typing import Generator

from sqlalchemy.orm import Session

from src.database import SessionLocal


def get_db() -> Generator[Session, None, None]:
    """Yield a database session, closing it after the request completes.

    Use as a FastAPI dependency::

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
