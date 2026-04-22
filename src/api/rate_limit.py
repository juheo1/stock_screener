"""
src.api.rate_limit
==================
Shared rate-limiter instance used by the FastAPI app and individual routers.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])
