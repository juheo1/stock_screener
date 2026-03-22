"""
src.ingestion.etf
=================
ETF metadata registry and yfinance-based live data fetcher.

The ETF list is loaded from ``data/famous_etf_tickers.txt`` and descriptions
from ``data/famous_etf_tickers_description.txt``.  Live metrics (expense ratio,
AUM, P/E, yield, returns) are fetched from yfinance with a 5-minute in-process
cache to avoid hammering the network on every filter change.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_TICKERS_FILE = _DATA_DIR / "famous_etf_tickers.txt"
_DESCRIPTIONS_FILE = _DATA_DIR / "famous_etf_tickers_description.txt"
# Persists custom-added ETF tickers and their names across server restarts
_CUSTOM_TICKERS_FILE = _DATA_DIR / "custom_etf_tickers.json"

# ---------------------------------------------------------------------------
# ETF group registry
# Mirrors the "sections" described in famous_etf_tickers_description.txt.
# ---------------------------------------------------------------------------

ETF_GROUPS: dict[str, dict] = {
    "all":        {"label": "All ETFs",      "tickers": []},  # filled at load
    "us_large":   {"label": "S&P 500",       "tickers": ["SPY"]},
    "us_growth":  {"label": "Nasdaq-100",    "tickers": ["QQQ"]},
    "us_total":   {"label": "Total Market",  "tickers": ["VTI"]},
    "us_small":   {"label": "Small Cap",     "tickers": ["IWM"]},
    "intl":       {"label": "International", "tickers": ["VXUS", "VEA", "IEMG"]},
    "bonds":      {"label": "Bonds",         "tickers": ["BND", "AGG"]},
    "realestate": {"label": "Real Estate",   "tickers": ["VNQ"]},
}

# Ticker → category label (reverse lookup built at load time)
_TICKER_CATEGORY: dict[str, str] = {}

# Ticker → short description text
ETF_DESCRIPTIONS: dict[str, str] = {}

# Ticker → full ETF name
ETF_NAMES: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Registry loading
# ---------------------------------------------------------------------------

def _read_custom_tickers() -> dict[str, str]:
    """Return ``{ticker: name}`` from the custom tickers JSON file."""
    if _CUSTOM_TICKERS_FILE.exists():
        try:
            return json.loads(_CUSTOM_TICKERS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _write_custom_tickers(mapping: dict[str, str]) -> None:
    """Persist ``{ticker: name}`` to the custom tickers JSON file."""
    _CUSTOM_TICKERS_FILE.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _load_registry() -> None:
    """Populate group and description lookups from the data text files."""
    # All-tickers list from tickers file
    if _TICKERS_FILE.exists():
        tickers = [
            t.strip().upper()
            for t in _TICKERS_FILE.read_text(encoding="utf-8").splitlines()
            if t.strip()
        ]
        ETF_GROUPS["all"]["tickers"] = tickers
    else:
        logger.warning("ETF tickers file not found: %s", _TICKERS_FILE)

    # Build reverse lookup: ticker → group label
    for group_key, group in ETF_GROUPS.items():
        if group_key == "all":
            continue
        for ticker in group["tickers"]:
            _TICKER_CATEGORY[ticker] = group["label"]

    # Parse descriptions
    if _DESCRIPTIONS_FILE.exists():
        _parse_descriptions(_DESCRIPTIONS_FILE.read_text(encoding="utf-8"))
    else:
        logger.warning("ETF descriptions file not found: %s", _DESCRIPTIONS_FILE)

    # Restore custom-added ETF group entries from the persisted JSON file.
    # These are tickers that were added via add_etf_ticker() and need their
    # own group entry in ETF_GROUPS so the frontend dropdown shows them.
    custom = _read_custom_tickers()
    for sym, name in custom.items():
        ETF_NAMES.setdefault(sym, name)
        if sym not in ETF_GROUPS:
            ETF_GROUPS[sym] = {"label": name, "tickers": [sym], "custom": True}


def _parse_descriptions(text: str) -> None:
    """Extract per-ticker names and descriptions from the free-form text file.

    Each ETF block starts with a line of the form ``TICKER - Full Name``,
    followed by one or more description sentences, then a blank line.
    """
    lines = text.splitlines()
    current_ticker: str | None = None
    current_name: str | None = None
    desc_lines: list[str] = []

    def _flush() -> None:
        if current_ticker:
            ETF_DESCRIPTIONS[current_ticker] = " ".join(desc_lines).strip()
            ETF_NAMES[current_ticker] = current_name or current_ticker

    for line in lines:
        stripped = line.strip()
        # Detect header lines: "SPY - SPDR S&P 500 ETF Trust"
        if " - " in stripped and len(stripped) < 100:
            parts = stripped.split(" - ", 1)
            candidate = parts[0].strip().upper()
            if 2 <= len(candidate) <= 5 and candidate.isalpha():
                _flush()
                desc_lines = []
                current_ticker = candidate
                current_name = parts[1].strip()
                continue
        if current_ticker and stripped:
            desc_lines.append(stripped)

    _flush()


_load_registry()


# ---------------------------------------------------------------------------
# Index constituent registries
# Hardcoded top-100 tickers per index by approximate market cap (2024/2025).
# Used for stock-mode display on the ETF screener page.
# ---------------------------------------------------------------------------

# Mapping from well-known Korean ETF tickers to their benchmark index key.
# Used as a fallback when pykrx is unavailable or incompatible.
_KOREAN_ETF_INDEX_MAP: dict[str, str] = {
    "102110.KS": "kospi200",  # TIGER 200
    "069500.KS": "kospi200",  # KODEX 200
    "278530.KS": "kospi200",  # KODEX 200ESG
    "148020.KS": "kospi200",  # KINDEX 200
    "252670.KS": "kospi200",  # KODEX 200선물인버스2X (inverse, same basket)
    "122630.KS": "kospi200",  # KODEX 레버리지 (leveraged KOSPI200)
}

INDEX_CONSTITUENTS: dict[str, list[str]] = {
    "kospi200": [  # KOSPI 200 – top 100 Korean stocks by market cap (2024/2025)
        "005930.KS", "000660.KS", "373220.KS", "207940.KS", "005380.KS",
        "000270.KS", "105560.KS", "068270.KS", "005490.KS", "055550.KS",
        "035420.KS", "035720.KS", "012330.KS", "051910.KS", "028260.KS",
        "086790.KS", "006400.KS", "066570.KS", "003670.KS", "032830.KS",
        "017670.KS", "033780.KS", "010130.KS", "034730.KS", "030200.KS",
        "096770.KS", "316140.KS", "009150.KS", "012450.KS", "138040.KS",
        "011200.KS", "015760.KS", "326030.KS", "323410.KS", "259960.KS",
        "090430.KS", "011170.KS", "097950.KS", "004020.KS", "009540.KS",
        "000810.KS", "010950.KS", "034020.KS", "047050.KS", "000720.KS",
        "002790.KS", "005940.KS", "018260.KS", "006360.KS", "021240.KS",
        "000100.KS", "008770.KS", "024110.KS", "010620.KS", "002380.KS",
        "051600.KS", "036570.KS", "032640.KS", "004490.KS", "003490.KS",
        "020150.KS", "009830.KS", "051900.KS", "267250.KS", "003550.KS",
        "377300.KS", "018880.KS", "004140.KS", "139480.KS", "006770.KS",
        "011780.KS", "023530.KS", "000080.KS", "001040.KS", "000120.KS",
        "010140.KS", "011070.KS", "014820.KS", "016360.KS", "028050.KS",
        "352820.KS", "003600.KS", "010060.KS", "007070.KS", "014990.KS",
        "000990.KS", "180640.KS", "069960.KS", "005830.KS", "005850.KS",
        "002720.KS", "006280.KS", "042700.KS", "000150.KS", "001570.KS",
        "004370.KS", "008000.KS", "000670.KS", "004430.KS", "016380.KS",
    ],
    "us_large": [  # S&P 500 – top 100 by market cap
        "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "BRK-B", "TSLA", "AVGO",
        "JPM", "LLY", "V", "XOM", "MA", "COST", "UNH", "HD", "ORCL", "NFLX",
        "WMT", "BAC", "JNJ", "CRM", "CVX", "ABBV", "MRK", "TMUS", "AMD", "KO",
        "WFC", "TMO", "CSCO", "ACN", "PEP", "NOW", "PM", "MCD", "ABT", "GE",
        "ISRG", "TXN", "IBM", "CAT", "AMGN", "SPGI", "LIN", "DHR", "BX", "NEE",
        "MS", "GS", "RTX", "HON", "BLK", "BKNG", "AXP", "REGN", "DE", "VRTX",
        "ADI", "LRCX", "SYK", "MMC", "PANW", "BSX", "PGR", "ETN", "MDT", "CB",
        "GILD", "AMAT", "C", "SO", "TJX", "MO", "MDLZ", "SBUX", "ADP", "DUK",
        "INTU", "CI", "HCA", "CL", "ZTS", "ELV", "APH", "EOG", "ITW", "CME",
        "NOC", "WM", "FI", "PH", "USB", "MCO", "GD", "KLAC", "FITB", "NSC",
    ],
    "us_growth": [  # Nasdaq-100 – top 100 by market cap
        "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "TSLA", "AVGO", "COST",
        "NFLX", "AMD", "TMUS", "QCOM", "ADBE", "INTU", "PEP", "CSCO", "HON", "GILD",
        "AMAT", "CMCSA", "SBUX", "BKNG", "ADI", "ISRG", "LRCX", "MU", "REGN", "SNPS",
        "CDNS", "MDLZ", "PANW", "KLAC", "FTNT", "MELI", "ADP", "VRTX", "INTC", "PYPL",
        "CTAS", "MRVL", "PCAR", "ABNB", "ORLY", "AZN", "CRWD", "IDXX", "ODFL", "FAST",
        "ROST", "CPRT", "GEHC", "KHC", "EXC", "DXCM", "XEL", "MRNA", "ON", "CDW",
        "DLTR", "CEG", "FANG", "ZS", "ANSS", "TEAM", "VRSK", "ROP", "EA", "WDAY",
        "BIIB", "CHTR", "PAYX", "ALGN", "CTSH", "ENPH", "NXPI", "ASML", "LULU", "EBAY",
        "MNST", "TTD", "DDOG", "NET", "SNOW", "PLTR", "ARM", "APP", "COIN", "SMCI",
        "PDD", "SIRI", "ILMN", "TTWO", "GFS", "GEN", "QRVO", "MCHP", "WBD", "RIVN",
    ],
    "us_total": [  # Total Market (VTI) – top 100 by market cap
        "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "BRK-B", "TSLA", "AVGO",
        "JPM", "LLY", "V", "XOM", "MA", "COST", "UNH", "HD", "ORCL", "NFLX",
        "WMT", "BAC", "JNJ", "CRM", "CVX", "ABBV", "MRK", "TMUS", "AMD", "KO",
        "WFC", "TMO", "CSCO", "ACN", "PEP", "NOW", "PM", "MCD", "ABT", "GE",
        "ISRG", "TXN", "IBM", "CAT", "AMGN", "SPGI", "LIN", "DHR", "BX", "NEE",
        "MS", "GS", "RTX", "HON", "BLK", "BKNG", "AXP", "REGN", "DE", "VRTX",
        "ADI", "LRCX", "SYK", "MMC", "PANW", "BSX", "PGR", "ETN", "MDT", "CB",
        "GILD", "AMAT", "C", "SO", "TJX", "MO", "MDLZ", "SBUX", "ADP", "DUK",
        "INTU", "CI", "HCA", "CL", "ZTS", "ELV", "APH", "EOG", "ITW", "CME",
        "NOC", "WM", "FI", "PH", "USB", "MCO", "GD", "KLAC", "FITB", "NSC",
    ],
    "us_small": [  # Small / Mid-Cap (IWM representative) – curated tickers
        "DECK", "AXON", "VEEV", "HUBS", "SFM", "FND", "CAVA", "ELF", "SAIA", "CELH",
        "BURL", "FIVE", "CHWY", "YETI", "SAIC", "CACI", "LHX", "TDY", "AMETEK", "NVT",
        "FTV", "PAYC", "PCTY", "GNRC", "WSM", "WING", "SHAK", "CMG", "DT", "BILL",
        "ESTC", "MQ", "HOOD", "SOFI", "RIVN", "ENPH", "RUN", "SEDG", "FSLR", "BOOT",
        "HIMS", "DKNG", "CROX", "ONON", "CART", "APP", "TTD", "GTLB", "DDOG", "NET",
        "ZS", "SNOW", "PLTR", "MNDY", "CFLT", "MGM", "WYNN", "CZR", "RCL", "CCL",
        "NCLH", "HLT", "MAR", "CHH", "BWXT", "CW", "MGA", "APTV", "LKQ", "BC",
        "LEN", "DHI", "NVR", "PHM", "TOL", "TMHC", "MDC", "LGIH", "SKY", "CVCO",
        "SPSC", "IOSP", "MYRG", "PRFT", "OMCL", "CRVL", "TNET", "MGRC", "AAON", "EXPO",
        "CSWI", "EPRT", "GRBK", "CTRE", "FCNCA", "MGEE", "PLXS", "DORM", "WRLD", "GFF",
    ],
    "intl": [  # International – major ADRs on US exchanges
        "TSM", "ASML", "NVO", "AZN", "SNY", "SAP", "NVS", "BABA", "SONY", "TM",
        "HMC", "UL", "BP", "BTI", "TCOM", "SE", "PDD", "JD", "BIDU", "NTES",
        "TME", "NU", "MELI", "KB", "SHG", "SKM", "INFY", "WIT", "RIO", "BHP",
        "NEM", "FCX", "GOLD", "SCCO", "DEO", "BUD", "STZ", "SHOP", "CP", "CNR",
        "TD", "RY", "BMO", "BNS", "ENB", "TRP", "SU", "CNQ", "CVE", "IMO",
        "VALE", "PBR", "ITUB", "BBD", "ABEV", "SID", "GGB", "CIB", "BSBR", "IQ",
        "VIPS", "FUTU", "QFIN", "LU", "YMM", "XPEV", "NIO", "LI", "LSPD", "DSGX",
        "MG", "RCI", "BCE", "OTEX", "GSK", "SHEL", "TTE", "E", "ERIC", "NOK",
        "ORAN", "TEF", "PHG", "STM", "IBN", "HDB", "RY", "TD", "BMO", "BNS",
        "VALE", "PBR", "ITUB", "NU", "MELI", "ABEV", "BSBR", "GGB", "CIB", "SID",
    ],
}


def fetch_etf_holdings(ticker: str, max_n: int = 100) -> list[str]:
    """Fetch the top holdings of an ETF from yfinance (5-min TTL cache).

    Uses ``yf.Ticker.funds_data.top_holdings`` to retrieve constituent
    symbols.  For Korean-market ETFs (suffix ``.KS`` / ``.KQ``) the
    holdings are often returned as bare numeric codes; the correct exchange
    suffix is appended automatically.

    Parameters
    ----------
    ticker : str
        ETF ticker, e.g. ``"102110.KS"`` or ``"SPY"``.
    max_n : int
        Maximum number of holding symbols to return.

    Returns
    -------
    list[str]
        Deduplicated constituent ticker symbols, up to ``max_n``.
    """
    sym = ticker.strip().upper()
    now = time.monotonic()
    if sym in _HOLDINGS_CACHE and now - _HOLDINGS_CACHE_TS.get(sym, 0) < _CACHE_TTL:
        return _HOLDINGS_CACHE[sym][:max_n]

    # Determine exchange suffix so bare numeric codes can be qualified
    suffix = ""
    if sym.endswith(".KS"):
        suffix = ".KS"
    elif sym.endswith(".KQ"):
        suffix = ".KQ"

    is_korean = sym.endswith(".KS") or sym.endswith(".KQ")
    krx_code  = sym.split(".")[0] if is_korean else None

    syms: list[str] = []
    seen: set[str] = set()

    # --- Path 1: Known Korean ETF index mapping (hardcoded, always available) ---
    if is_korean:
        index_key = _KOREAN_ETF_INDEX_MAP.get(sym)
        if index_key and index_key in INDEX_CONSTITUENTS:
            constituents = INDEX_CONSTITUENTS[index_key]
            result = list(dict.fromkeys(constituents))[:max_n]
            _HOLDINGS_CACHE[sym] = result
            _HOLDINGS_CACHE_TS[sym] = now
            return result

    # --- Path 2: pykrx (Korean ETFs not in the hardcoded map) ---
    if is_korean and krx_code:
        try:
            from pykrx import stock as krx_stock  # optional dependency
            import datetime
            # pykrx public API: get_etf_portfolio_deposit_file(ticker, date)
            for delta in range(5):
                date = (datetime.date.today() - datetime.timedelta(days=delta)).strftime("%Y%m%d")
                try:
                    pdf_df = krx_stock.get_etf_portfolio_deposit_file(krx_code, date)
                    if pdf_df is not None and not pdf_df.empty:
                        for code in pdf_df.index:
                            code = str(code).strip()
                            if code.isdigit():
                                full = code + suffix
                                if full not in seen:
                                    seen.add(full)
                                    syms.append(full)
                        break  # got data — stop retrying
                except Exception:
                    continue
        except ImportError:
            logger.warning(
                "fetch_etf_holdings(%s): pykrx is not installed. "
                "Run 'pip install pykrx' to enable Korean ETF holdings lookup.", sym
            )
        except Exception as exc:
            logger.warning("fetch_etf_holdings(%s) pykrx unavailable: %s", sym, exc)

    # --- Path 2: yfinance funds_data (works for US/global ETFs, not Korean) ---
    if not syms:
        try:
            t = yf.Ticker(sym)
            holdings_df = t.funds_data.top_holdings
            if holdings_df is not None and not holdings_df.empty:
                col = next((c for c in ["symbol", "Symbol", "Ticker"] if c in holdings_df.columns), None)
                raw = holdings_df[col].dropna().tolist() if col else [str(i) for i in holdings_df.index]
                for s in raw:
                    s = str(s).strip()
                    if not s:
                        continue
                    if suffix and s.isdigit():
                        s = s + suffix
                    if s not in seen:
                        seen.add(s)
                        syms.append(s)
        except Exception as exc:
            logger.error("fetch_etf_holdings(%s) yfinance failed: %s", sym, exc)

    _HOLDINGS_CACHE[sym] = syms
    _HOLDINGS_CACHE_TS[sym] = now
    return syms[:max_n]


def get_index_constituent_tickers(group: str, max_n: int = 100) -> list[str]:
    """Return the top-N constituent tickers for an index group.

    For predefined groups (e.g. ``"us_large"``) the hardcoded
    ``INDEX_CONSTITUENTS`` list is used.  For custom-added ETF groups the
    holdings are fetched live from yfinance.

    Parameters
    ----------
    group : str
        Index group key or custom ETF ticker (e.g. ``"us_large"``,
        ``"102110.KS"``).
    max_n : int
        Maximum number of tickers to return.

    Returns
    -------
    list[str]
        Ticker symbols, deduplicated, up to ``max_n``.
    """
    # Predefined index — use the hardcoded list
    if group in INDEX_CONSTITUENTS:
        tickers = INDEX_CONSTITUENTS[group]
        seen: set[str] = set()
        unique: list[str] = []
        for t in tickers:
            if t not in seen:
                seen.add(t)
                unique.append(t)
            if len(unique) >= max_n:
                break
        return unique

    # Custom-added ETF — check if it maps to a known index first
    if group in ETF_GROUPS and ETF_GROUPS[group].get("custom"):
        index_key = _KOREAN_ETF_INDEX_MAP.get(group)
        if index_key and index_key in INDEX_CONSTITUENTS:
            constituents = INDEX_CONSTITUENTS[index_key]
            return list(dict.fromkeys(constituents))[:max_n]  # deduplicate, preserve order
        # Fall back to live holdings fetch (yfinance / pykrx)
        return fetch_etf_holdings(group, max_n=max_n)

    return []


# ---------------------------------------------------------------------------
# In-process TTL caches
# ---------------------------------------------------------------------------

_CACHE: dict[str, list[dict]] = {}          # ETF metrics cache; key = comma-joined tickers
_CACHE_TS: dict[str, float] = {}
_HOLDINGS_CACHE: dict[str, list[str]] = {}  # ETF holdings cache; key = ETF ticker
_HOLDINGS_CACHE_TS: dict[str, float] = {}
_CACHE_TTL = 300                            # seconds (5 minutes)


# ---------------------------------------------------------------------------
# yfinance fetcher
# ---------------------------------------------------------------------------

def reload_custom_groups() -> None:
    """Re-read ``custom_etf_tickers.json`` and restore any missing group entries.

    If a stored name equals the ticker symbol (i.e. it was never properly
    resolved), a live yfinance lookup is attempted so the dropdown shows the
    real fund name.  Any resolved names are written back to the JSON file.

    Called by the refresh endpoint so custom-added tickers reappear in the
    dropdown without a full server restart.
    """
    custom = _read_custom_tickers()
    changed = False

    for sym, name in list(custom.items()):
        # Placeholder name == ticker symbol means the real name was never fetched
        if name == sym:
            try:
                info = yf.Ticker(sym).info or {}
                real_name = info.get("longName") or info.get("shortName")
                if real_name and real_name != sym:
                    name = real_name
                    custom[sym] = name
                    changed = True
            except Exception as exc:
                logger.warning("reload_custom_groups: could not resolve name for %s: %s", sym, exc)

        ETF_NAMES[sym] = name  # always refresh in-memory name
        if sym not in ETF_GROUPS["all"]["tickers"]:
            ETF_GROUPS["all"]["tickers"].append(sym)
        if sym not in ETF_GROUPS:
            ETF_GROUPS[sym] = {"label": name, "tickers": [sym], "custom": True}
        else:
            ETF_GROUPS[sym]["label"] = name  # update label if name just resolved

    if changed:
        _write_custom_tickers(custom)


def bust_cache() -> None:
    """Clear all in-process ETF caches, forcing a full re-fetch on next call."""
    _CACHE.clear()
    _CACHE_TS.clear()
    _HOLDINGS_CACHE.clear()
    _HOLDINGS_CACHE_TS.clear()


def _validate_ticker_yfinance(sym: str) -> tuple[bool, dict]:
    """Return (is_valid, info_dict) for a yfinance ticker symbol.

    Validation strategy (in order):
    1. ``t.info`` with at least one non-null value beyond ``trailingPegRatio``
       (yfinance returns ``{"trailingPegRatio": None}`` for unknown symbols).
    2. Fallback: recent price history non-empty.
    """
    t = yf.Ticker(sym)
    try:
        info = t.info or {}
    except Exception:
        info = {}

    # yfinance returns {"trailingPegRatio": None} for invalid symbols
    meaningful_keys = {k for k, v in info.items() if v is not None and k != "trailingPegRatio"}
    if meaningful_keys:
        return True, info

    # Fallback: try fetching recent price history
    try:
        hist = t.history(period="5d")
        if not hist.empty:
            return True, info
    except Exception:
        pass

    return False, info


def add_etf_ticker(ticker: str) -> dict:
    """Add a ticker to the ETF list (in-memory and on disk).

    Supports any yfinance-compatible ticker symbol, including exchange-suffixed
    ones such as ``102110.KS`` (KRX) or ``247540.KQ`` (KOSDAQ).

    Korean market tickers **require** the exchange suffix:
    - ``.KS`` for KRX (Korea Stock Exchange)
    - ``.KQ`` for KOSDAQ

    Parameters
    ----------
    ticker : str
        Ticker symbol to add.  Exchange suffix is preserved as-is.

    Returns
    -------
    dict
        ``{"added": True}`` if the ticker was new, ``{"added": False}`` if it
        already existed.  Raises ``ValueError`` on validation failure.
    """
    sym = ticker.strip().upper()

    # Validate the ticker exists in yfinance
    is_valid, info = _validate_ticker_yfinance(sym)
    if not is_valid:
        # Provide a helpful hint for bare numeric tickers (Korean market)
        if sym.isdigit():
            hint = (
                f"Ticker '{sym}' not found. "
                f"For Korean market tickers add an exchange suffix, e.g. '{sym}.KS' (KRX) "
                f"or '{sym}.KQ' (KOSDAQ)."
            )
        else:
            hint = f"Ticker '{sym}' not found or returned no data from yfinance."
        raise ValueError(hint)

    if sym in ETF_GROUPS["all"]["tickers"]:
        return {"added": False}

    # Populate name from yfinance if not already known
    name = info.get("longName") or info.get("shortName") or sym
    if sym not in ETF_NAMES:
        ETF_NAMES[sym] = name

    ETF_GROUPS["all"]["tickers"].append(sym)
    # Register as its own group so the frontend dropdown reflects it
    ETF_GROUPS[sym] = {"label": name, "tickers": [sym], "custom": True}

    if _TICKERS_FILE.exists():
        with _TICKERS_FILE.open("a", encoding="utf-8") as f:
            f.write(f"\n{sym}")
    else:
        _TICKERS_FILE.write_text(sym, encoding="utf-8")

    # Persist name so the custom group survives server restarts
    custom = _read_custom_tickers()
    custom[sym] = name
    _write_custom_tickers(custom)

    bust_cache()
    return {"added": True}


def remove_etf_ticker(ticker: str) -> dict:
    """Remove a ticker from the ETF registry (in-memory and on disk).

    Removes the ticker from ``ETF_GROUPS["all"]``, deletes its custom group
    entry if present, rewrites ``famous_etf_tickers.txt``, and busts the
    in-process cache.

    Parameters
    ----------
    ticker : str
        Ticker symbol to remove.

    Returns
    -------
    dict
        ``{"removed": True}`` if the ticker was found and removed,
        ``{"removed": False}`` if it was not in the list.
    """
    sym = ticker.strip().upper()

    was_present = sym in ETF_GROUPS["all"]["tickers"]
    if not was_present:
        return {"removed": False}

    # Remove from the all-tickers list
    ETF_GROUPS["all"]["tickers"] = [t for t in ETF_GROUPS["all"]["tickers"] if t != sym]

    # Remove the custom per-ticker group entry if it exists
    if sym in ETF_GROUPS and ETF_GROUPS[sym].get("custom"):
        del ETF_GROUPS[sym]

    # Also clear from name/description lookups
    ETF_NAMES.pop(sym, None)
    ETF_DESCRIPTIONS.pop(sym, None)
    _TICKER_CATEGORY.pop(sym, None)

    # Rewrite the tickers file
    if _TICKERS_FILE.exists():
        lines = _TICKERS_FILE.read_text(encoding="utf-8").splitlines()
        kept = [ln for ln in lines if ln.strip().upper() != sym]
        _TICKERS_FILE.write_text("\n".join(kept), encoding="utf-8")

    # Remove from the custom tickers JSON file
    custom = _read_custom_tickers()
    if sym in custom:
        del custom[sym]
        _write_custom_tickers(custom)

    bust_cache()
    return {"removed": True}


def fetch_etf_data(tickers: list[str] | None = None) -> list[dict]:
    """Fetch live metrics for the given ETF tickers (defaults to all).

    Results are cached in-process for ``_CACHE_TTL`` seconds to avoid
    repeated yfinance calls on every filter change.

    Parameters
    ----------
    tickers : list[str] | None
        Subset of tickers to fetch.  ``None`` means all registered ETFs.

    Returns
    -------
    list[dict]
        One dict per ETF with keys: ``ticker``, ``name``, ``category``,
        ``description``, ``expense_ratio``, ``aum_b``, ``pe_ratio``,
        ``dividend_yield``, ``one_yr_return``, ``three_yr_return``.
        Numeric fields are ``float | None``.
    """
    if tickers is None:
        tickers = ETF_GROUPS["all"]["tickers"]

    cache_key = ",".join(tickers)
    now = time.monotonic()
    if cache_key in _CACHE and now - _CACHE_TS.get(cache_key, 0) < _CACHE_TTL:
        return _CACHE[cache_key]

    results: list[dict] = []
    for sym in tickers:
        results.append(_fetch_one(sym))

    _CACHE[cache_key] = results
    _CACHE_TS[cache_key] = now
    return results


def _fetch_one(sym: str) -> dict:
    """Fetch metrics for a single ETF ticker from yfinance.

    All percentage metrics are computed directly from price / dividend history
    rather than relying on yfinance ``.info`` fields, which return inconsistent
    units across ETF types (some already in %, others as ratios).
    """
    base = {
        "ticker":             sym,
        "name":               ETF_NAMES.get(sym, sym),
        "category":           _TICKER_CATEGORY.get(sym, "Other"),
        "description":        ETF_DESCRIPTIONS.get(sym, ""),
        "expense_ratio":      None,
        "aum_b":              None,
        "pe_ratio":           None,
        "dividend_yield":     None,
        "three_month_return": None,
        "six_month_return":   None,
        "one_yr_return":      None,
        "three_yr_return":    None,
    }
    try:
        t = yf.Ticker(sym)
        info = t.info or {}

        # Expense ratio — stored as a decimal ratio (0.0009 = 0.09%); multiply ×100
        expense_raw = info.get("annualReportExpenseRatio") or info.get("expenseRatio")
        if expense_raw is not None:
            base["expense_ratio"] = round(float(expense_raw) * 100, 4)

        # AUM / total assets
        total_assets = info.get("totalAssets")
        if total_assets:
            base["aum_b"] = round(float(total_assets) / 1e9, 2)

        # Trailing P/E — raw number, no unit conversion needed
        pe = info.get("trailingPE") or info.get("forwardPE")
        if pe:
            base["pe_ratio"] = round(float(pe), 2)

        # --- Returns and yield from price / dividend history (reliable units) ---

        # Fetch 3Y of daily closes once; reuse for 3M, 6M, 1Y and 3Y returns
        hist3y = t.history(period="3y", auto_adjust=True)

        if not hist3y.empty and len(hist3y) >= 2:
            last = hist3y.index[-1]

            # 3-month return
            hist_3m = hist3y[hist3y.index >= last - pd.DateOffset(months=3)]
            if len(hist_3m) >= 2:
                base["three_month_return"] = round(
                    float(hist_3m["Close"].iloc[-1] / hist_3m["Close"].iloc[0] - 1) * 100, 2
                )

            # 6-month return
            hist_6m = hist3y[hist3y.index >= last - pd.DateOffset(months=6)]
            if len(hist_6m) >= 2:
                base["six_month_return"] = round(
                    float(hist_6m["Close"].iloc[-1] / hist_6m["Close"].iloc[0] - 1) * 100, 2
                )

            # 1-year return
            hist_1y = hist3y[hist3y.index >= last - pd.DateOffset(years=1)]
            if len(hist_1y) >= 2:
                base["one_yr_return"] = round(
                    float(hist_1y["Close"].iloc[-1] / hist_1y["Close"].iloc[0] - 1) * 100, 2
                )

            # 3-year annualised return: (price_now / price_3y_ago)^(1/n_years) - 1
            total_r = hist3y["Close"].iloc[-1] / hist3y["Close"].iloc[0]
            n_years = (hist3y.index[-1] - hist3y.index[0]).days / 365.25
            if n_years >= 0.5:
                base["three_yr_return"] = round(
                    float(total_r ** (1.0 / n_years) - 1) * 100, 2
                )

        # Dividend yield: trailing 12-month distributions / current price
        current_price = (
            info.get("regularMarketPrice")
            or info.get("currentPrice")
            or info.get("previousClose")
        )
        if current_price:
            try:
                divs = t.dividends
                if not divs.empty:
                    one_year_ago = pd.Timestamp.now(tz=divs.index.tz) - pd.DateOffset(years=1)
                    trailing_divs = divs[divs.index >= one_year_ago].sum()
                    if trailing_divs > 0:
                        base["dividend_yield"] = round(
                            float(trailing_divs) / float(current_price) * 100, 3
                        )
            except Exception:
                pass  # dividends unavailable for this ETF

    except Exception as exc:
        logger.error("Failed to fetch ETF data for %s: %s", sym, exc)

    return base
