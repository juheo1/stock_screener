"""
src.api.deps
============
Shared FastAPI dependency functions.

Provides
--------
get_db        -- Yield a SQLAlchemy session (one per request).
require_admin -- Verify the caller has admin privileges.
"""

from __future__ import annotations

import logging
from typing import Generator

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from src.config import settings
from src.database import SessionLocal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Database session
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Admin API-key guard
# ---------------------------------------------------------------------------

_api_key_header = APIKeyHeader(name="X-Admin-API-Key", auto_error=False)


def require_admin(
    api_key: str | None = Security(_api_key_header),
) -> None:
    """Dependency that gates admin / destructive endpoints.

    Behaviour
    ---------
    * **Dev mode** (``DEV_MODE=true``, the default): all requests pass through
      without requiring an API key.  This is the expected mode when running
      locally via ``python scripts/run_server.py``.
    * **Production mode** (``DEV_MODE=false``): the request must include a
      header ``X-Admin-API-Key`` whose value matches ``ADMIN_API_KEY`` from
      the environment.  If the key is missing or wrong the endpoint returns
      ``403 Forbidden``.

    Raises
    ------
    HTTPException (403)
        When not in dev mode and the API key is missing or invalid.
    HTTPException (500)
        When not in dev mode and ``ADMIN_API_KEY`` is not configured.
    """
    if settings.dev_mode:
        return

    if not settings.admin_api_key:
        logger.error(
            "ADMIN_API_KEY is not set but DEV_MODE is false — "
            "admin endpoints are locked out."
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server misconfiguration: admin API key not set.",
        )

    if not api_key or api_key != settings.admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing admin API key.",
        )
