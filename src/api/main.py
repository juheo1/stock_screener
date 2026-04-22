"""
src.api.main
============
FastAPI application factory.

Run directly with uvicorn::

    uvicorn src.api.main:app --host 127.0.0.1 --port 8000 --reload

Or via the convenience script::

    python scripts/run_server.py
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from src.api.rate_limit import limiter
from src.config import settings
from src.database import init_db

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject standard security headers into every response."""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        if not settings.dev_mode:
            # In production, add a restrictive CSP.
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'"
            )
        return response


def create_app() -> FastAPI:
    """Build and configure the FastAPI application.

    Returns
    -------
    FastAPI
    """
    # Disable Swagger/ReDoc when not in dev mode
    docs_url = "/docs" if settings.dev_mode else None
    redoc_url = "/redoc" if settings.dev_mode else None

    app = FastAPI(
        title="Stock Intelligence & Screener API",
        description=(
            "Backend API for the local stock screener: "
            "equities, zombies, comparison, retirement modelling, metals, and macro."
        ),
        version="1.0.0",
        docs_url=docs_url,
        redoc_url=redoc_url,
    )

    # ---------------------------------------------------------------------------
    # Rate limiting
    # ---------------------------------------------------------------------------
    app.state.limiter = limiter

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Please try again later."},
        )

    # ---------------------------------------------------------------------------
    # CORS — allow Dash frontend running on a different port
    # ---------------------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            f"http://{settings.dash_host}:{settings.dash_port}",
            "http://localhost:8050",
            "http://127.0.0.1:8050",
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Admin-API-Key"],
    )

    # ---------------------------------------------------------------------------
    # Security headers
    # ---------------------------------------------------------------------------
    app.add_middleware(SecurityHeadersMiddleware)

    # ---------------------------------------------------------------------------
    # Lifecycle
    # ---------------------------------------------------------------------------

    @app.on_event("startup")
    def on_startup():
        init_db()
        logger.info("Database initialised.")
        try:
            from src.scheduler import start_scheduler
            start_scheduler()
        except Exception as exc:
            logger.warning("Scheduler could not start: %s", exc)

    @app.on_event("shutdown")
    def on_shutdown():
        try:
            from src.scheduler import stop_scheduler
            stop_scheduler()
        except Exception:
            pass

    # ---------------------------------------------------------------------------
    # Routers
    # ---------------------------------------------------------------------------
    from src.api.routers import (
        admin,
        calendar,
        compare,
        dashboard,
        disasters,
        etf,
        geopolitical,
        liquidity,
        macro,
        metals,
        news,
        retirement,
        scanner,
        screener,
        sentiment,
        trades,
        zombies,
    )

    app.include_router(dashboard.router)
    app.include_router(screener.router)
    app.include_router(etf.router)
    app.include_router(zombies.router)
    app.include_router(compare.router)
    app.include_router(retirement.router)
    app.include_router(metals.router)
    app.include_router(macro.router)
    app.include_router(liquidity.router)
    app.include_router(news.router)
    app.include_router(sentiment.router)
    app.include_router(disasters.router)
    app.include_router(geopolitical.router)
    app.include_router(calendar.router)
    app.include_router(scanner.router)
    app.include_router(trades.router)
    app.include_router(admin.router)

    @app.get("/", tags=["health"])
    def health_check():
        """API health check endpoint."""
        return {"status": "ok", "version": "1.0.0"}

    return app


app = create_app()
