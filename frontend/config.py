"""
frontend.config
===============
Runtime configuration for the Dash frontend.

Values are read from environment variables or a ``.env`` file.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

API_HOST: str = os.getenv("API_HOST", "127.0.0.1")
API_PORT: int = int(os.getenv("API_PORT", "8000"))
API_BASE_URL: str = f"http://{API_HOST}:{API_PORT}"

DASH_HOST: str = os.getenv("DASH_HOST", "127.0.0.1")
DASH_PORT: int = int(os.getenv("DASH_PORT", "8050"))
DASH_DEBUG: bool = os.getenv("DASH_DEBUG", "false").lower() == "true"
