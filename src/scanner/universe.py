"""
src.scanner.universe
====================
ETF-constituent universe resolution with deduplication and disk caching.

The resolved universe is a deduplicated list of tickers sourced from the
top holdings of a configurable set of ETFs.  Each ETF itself is also
included as a scan target.

Public API
----------
resolve_universe        Resolve ETF constituents; returns a UniverseSnapshot.
load_cached_universe    Load the cached universe from disk (if valid).
save_universe_cache     Persist a universe snapshot to disk.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "scanner"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_CACHE_FILE = _CACHE_DIR / "universe_cache.json"
_CACHE_TTL_DAYS = 7

# Default ETF universe (configurable via settings)
DEFAULT_SCANNER_ETFS: list[str] = [
    "SPY",   # S&P 500
    "QQQ",   # Nasdaq-100
    "VTI",   # Total US Market
    "IWM",   # Russell 2000
    "VXUS",  # International ex-US
    "VEA",   # Developed Markets
    "IEMG",  # Emerging Markets
    "VNQ",   # US REITs
]


@dataclass
class UniverseSnapshot:
    """Resolved and deduplicated scan universe.

    Attributes
    ----------
    tickers:
        Sorted list of unique ticker symbols to scan.
    ticker_to_etfs:
        Maps each ticker to the list of source ETFs it belongs to.
    source_etfs:
        The ETF tickers used to build this universe.
    resolved_at:
        ISO-format UTC timestamp of resolution.
    """
    tickers: list[str]
    ticker_to_etfs: dict[str, list[str]]
    source_etfs: list[str]
    resolved_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "UniverseSnapshot":
        return cls(
            tickers=d["tickers"],
            ticker_to_etfs=d["ticker_to_etfs"],
            source_etfs=d["source_etfs"],
            resolved_at=d.get("resolved_at", ""),
        )


def resolve_universe(
    etf_tickers: list[str] | None = None,
    *,
    use_cache: bool = True,
    max_holdings_per_etf: int = 100,
) -> UniverseSnapshot:
    """Resolve ETF constituents into a deduplicated scan universe.

    Parameters
    ----------
    etf_tickers:
        List of ETF symbols to use.  Defaults to :data:`DEFAULT_SCANNER_ETFS`.
    use_cache:
        If True, return a cached snapshot when it is still within TTL.
    max_holdings_per_etf:
        Maximum number of holdings to fetch per ETF.

    Returns
    -------
    UniverseSnapshot with deduplicated tickers and ETF membership metadata.
    """
    if etf_tickers is None:
        etf_tickers = DEFAULT_SCANNER_ETFS

    if use_cache:
        cached = load_cached_universe(etf_tickers)
        if cached is not None:
            logger.info(
                "[Universe] Using cached universe (%d tickers, resolved %s)",
                len(cached.tickers), cached.resolved_at,
            )
            return cached

    logger.info("[Universe] Resolving universe from %d ETFs ...", len(etf_tickers))
    ticker_to_etfs: dict[str, list[str]] = {}

    for etf in etf_tickers:
        try:
            holdings = _fetch_holdings(etf, max_n=max_holdings_per_etf)
            for h in holdings:
                ticker_to_etfs.setdefault(h, []).append(etf)
            # Include the ETF itself
            ticker_to_etfs.setdefault(etf, []).append(etf)
            logger.debug("[Universe] %s: %d holdings", etf, len(holdings))
        except Exception as exc:
            logger.warning("[Universe] Failed to fetch holdings for %s: %s", etf, exc)
            # Still include the ETF itself even if holdings fail
            ticker_to_etfs.setdefault(etf, []).append(etf)

    snapshot = UniverseSnapshot(
        tickers=sorted(ticker_to_etfs.keys()),
        ticker_to_etfs=ticker_to_etfs,
        source_etfs=etf_tickers,
    )
    logger.info("[Universe] Resolved %d unique tickers from %d ETFs",
                len(snapshot.tickers), len(etf_tickers))

    save_universe_cache(snapshot)
    return snapshot


def load_cached_universe(etf_tickers: list[str] | None = None) -> UniverseSnapshot | None:
    """Load the cached universe from disk if it is still valid.

    Returns ``None`` if the cache does not exist, is expired, or was built
    from a different set of ETFs.
    """
    if not _CACHE_FILE.is_file():
        return None
    try:
        data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        resolved_at_str = data.get("resolved_at", "")
        resolved_at = datetime.fromisoformat(resolved_at_str)
        # Ensure timezone-aware comparison
        if resolved_at.tzinfo is None:
            resolved_at = resolved_at.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - resolved_at).total_seconds() / 86400
        if age_days > _CACHE_TTL_DAYS:
            logger.debug("[Universe] Cache expired (%.1f days old)", age_days)
            return None
        # Check ETF set matches if provided
        if etf_tickers is not None:
            cached_etfs = sorted(data.get("source_etfs", []))
            if cached_etfs != sorted(etf_tickers):
                logger.debug("[Universe] Cache ETF set mismatch; re-resolving")
                return None
        return UniverseSnapshot.from_dict(data)
    except Exception as exc:
        logger.warning("[Universe] Cache load failed: %s", exc)
        return None


def save_universe_cache(snapshot: UniverseSnapshot) -> None:
    """Write a universe snapshot to the disk cache."""
    try:
        _CACHE_FILE.write_text(
            json.dumps(snapshot.to_dict(), indent=2),
            encoding="utf-8",
        )
        logger.debug("[Universe] Cache saved to %s", _CACHE_FILE)
    except Exception as exc:
        logger.warning("[Universe] Cache write failed: %s", exc)


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _fetch_holdings(etf: str, max_n: int = 100) -> list[str]:
    """Fetch ETF holdings via src.ingestion.etf.fetch_etf_holdings."""
    from src.ingestion.etf import fetch_etf_holdings
    return fetch_etf_holdings(etf, max_n=max_n)
