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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.database import init_db

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Build and configure the FastAPI application.

    Returns
    -------
    FastAPI
    """
    app = FastAPI(
        title="Stock Intelligence & Screener API",
        description=(
            "Backend API for the local stock screener: "
            "equities, zombies, comparison, retirement modelling, metals, and macro."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
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
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
        screener,
        sentiment,
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
    app.include_router(admin.router)

    @app.get("/", tags=["health"])
    def health_check():
        """API health check endpoint."""
        return {"status": "ok", "version": "1.0.0"}

    return app


app = create_app()
