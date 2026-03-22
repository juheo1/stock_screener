"""
scripts/run_server.py
=====================
Convenience launcher: starts the FastAPI backend and the Dash frontend
as separate processes, then waits for both to exit (Ctrl+C stops both).

Usage
-----
    python scripts/run_server.py               # start both servers
    python scripts/run_server.py --api-only    # FastAPI only
    python scripts/run_server.py --frontend-only  # Dash only

Arguments
---------
--api-only        Start only the FastAPI/uvicorn server.
--frontend-only   Start only the Dash frontend.
--reload          Enable hot-reload for FastAPI (development mode).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import os
import time
import signal
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PYTHON = sys.executable


def start_api(reload: bool = False) -> subprocess.Popen:
    """Start the FastAPI/uvicorn process.

    Parameters
    ----------
    reload : bool
        Enable uvicorn hot-reload.

    Returns
    -------
    subprocess.Popen
    """
    cmd = [
        PYTHON, "-m", "uvicorn",
        "src.api.main:app",
        "--host", settings.api_host,
        "--port", str(settings.api_port),
    ]
    if reload:
        cmd.append("--reload")

    logger.info("Starting FastAPI at http://%s:%d", settings.api_host, settings.api_port)
    return subprocess.Popen(cmd, cwd=PROJECT_ROOT)


def start_frontend() -> subprocess.Popen:
    """Start the Dash frontend process.

    Returns
    -------
    subprocess.Popen
    """
    logger.info(
        "Starting Dash frontend at http://%s:%d",
        settings.dash_host, settings.dash_port,
    )
    return subprocess.Popen(
        [PYTHON, "frontend/app.py"],
        cwd=PROJECT_ROOT,
    )


def main() -> None:
    """Parse arguments, launch processes, and wait."""
    parser = argparse.ArgumentParser(description="Start stock screener servers.")
    parser.add_argument("--api-only",      action="store_true", help="Start API only.")
    parser.add_argument("--frontend-only", action="store_true", help="Start frontend only.")
    parser.add_argument("--reload",        action="store_true", help="Hot-reload FastAPI.")
    args = parser.parse_args()

    procs: list[subprocess.Popen] = []

    if not args.frontend_only:
        procs.append(start_api(reload=args.reload))
        # Give API a moment to start before the frontend tries to connect
        time.sleep(2)

    if not args.api_only:
        procs.append(start_frontend())

    logger.info(
        "\n\n  FastAPI docs: http://%s:%d/docs\n  Dash UI:      http://%s:%d\n\n"
        "  Press Ctrl+C to stop.\n",
        settings.api_host, settings.api_port,
        settings.dash_host, settings.dash_port,
    )

    def _shutdown(sig, frame):
        logger.info("Shutting down...")
        for p in procs:
            p.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    for p in procs:
        p.wait()


if __name__ == "__main__":
    main()
