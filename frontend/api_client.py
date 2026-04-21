"""
frontend.api_client
===================
Thin helper layer for calling the FastAPI backend from Dash callbacks.

All functions return Python dicts / lists (parsed JSON) and log errors
rather than raising, so the UI can display a friendly empty state.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from frontend.config import API_BASE_URL

logger = logging.getLogger(__name__)

_TIMEOUT = 15        # seconds — normal API calls
_RETIREMENT_TIMEOUT = 60   # seconds — MC simulation (cached: <1s, true random: ~5s)
_ADMIN_TIMEOUT = 300  # seconds — fetch/compute can take several minutes for many tickers


def _get(path: str, params: dict | None = None) -> Any:
    """Make a GET request to the API.

    Parameters
    ----------
    path : str
        Endpoint path (e.g. ``"/dashboard"``).
    params : dict | None
        Query parameters.

    Returns
    -------
    Any
        Parsed JSON response, or ``None`` on error.
    """
    url = f"{API_BASE_URL}{path}"
    try:
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        logger.error("Cannot connect to API at %s — is the server running?", API_BASE_URL)
        return None
    except Exception as exc:
        logger.error("GET %s failed: %s", path, exc)
        return None


def _post(path: str, body: dict, timeout: int = _TIMEOUT) -> Any:
    """Make a POST request to the API.

    Parameters
    ----------
    path : str
    body : dict
        JSON request body.

    Returns
    -------
    Any
        Parsed JSON response, or ``None`` on error.
    """
    url = f"{API_BASE_URL}{path}"
    try:
        resp = requests.post(url, json=body, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.error("POST %s failed: %s", path, exc)
        return None


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def get_dashboard() -> dict | None:
    """Fetch the Intelligence Hub summary data."""
    return _get("/dashboard")


# ---------------------------------------------------------------------------
# Screener
# ---------------------------------------------------------------------------

def get_screener(
    min_gross_margin=None,
    min_roic=None,
    min_fcf_margin=None,
    min_interest_coverage=None,
    max_pe=None,
    min_score=None,
    hide_na=False,
    sort_by="gross_margin",
    sort_dir="desc",
    page=1,
    page_size=50,
    period_type="quarterly",
    region: str | None = None,
) -> dict | None:
    """Fetch filtered screener results."""
    params = {k: v for k, v in {
        "min_gross_margin": min_gross_margin,
        "min_roic": min_roic,
        "min_fcf_margin": min_fcf_margin,
        "min_interest_coverage": min_interest_coverage,
        "max_pe": max_pe,
        "min_score": min_score,
        "hide_na": hide_na,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
        "page": page,
        "page_size": page_size,
        "period_type": period_type,
        "region": region,
    }.items() if v is not None}
    return _get("/screener", params=params)


def get_presets() -> list | None:
    """Fetch built-in screening presets."""
    return _get("/presets")


# ---------------------------------------------------------------------------
# ETF Screener
# ---------------------------------------------------------------------------

def get_etf_screener(
    group: str | None = None,
    max_expense_ratio: float | None = None,
    min_dividend_yield: float | None = None,
    min_one_yr_return: float | None = None,
    min_three_yr_return: float | None = None,
    min_aum_b: float | None = None,
    max_pe: float | None = None,
    hide_na: bool = False,
) -> dict | None:
    """Fetch filtered ETF screener results."""
    params = {k: v for k, v in {
        "group": group,
        "max_expense_ratio": max_expense_ratio,
        "min_dividend_yield": min_dividend_yield,
        "min_one_yr_return": min_one_yr_return,
        "min_three_yr_return": min_three_yr_return,
        "min_aum_b": min_aum_b,
        "max_pe": max_pe,
        "hide_na": hide_na,
    }.items() if v is not None and v is not False}
    return _get("/etf", params=params)


def get_etf_groups() -> dict | None:
    """Fetch ETF group definitions."""
    return _get("/etf/groups")


def admin_refresh_etf() -> dict | None:
    """Bust the server-side ETF metrics cache."""
    return _post("/etf/refresh", {})


def admin_add_etf_ticker(ticker: str) -> dict | None:
    """Add a ticker to the ETF list (validated via yfinance on the server).

    Supports exchange-suffixed tickers, e.g. ``102110.KS`` or ``247540.KQ``.
    Returns:
      - ``{"added": True/False, "ticker": sym}`` on success
      - ``{"error": "<detail>"}`` when the server rejects the ticker (404/422)
      - ``None`` on network/connection error
    """
    url = f"{API_BASE_URL}/etf/add_ticker"
    try:
        resp = requests.post(url, json={"ticker": ticker.strip().upper()}, timeout=_ADMIN_TIMEOUT)
        if resp.ok:
            return resp.json()
        # Surface the server's error detail (e.g. hint about .KS suffix)
        try:
            detail = resp.json().get("detail", resp.reason)
        except Exception:
            detail = resp.reason
        return {"error": detail}
    except requests.exceptions.ConnectionError:
        logger.error("Cannot connect to API at %s — is the server running?", API_BASE_URL)
        return None
    except Exception as exc:
        logger.error("POST /etf/add_ticker failed: %s", exc)
        return None


def admin_remove_etf_ticker(ticker: str) -> dict | None:
    """Remove a ticker from the ETF registry (in-memory + disk).

    This targets the ETF list, not the stock fundamentals database.
    Returns a dict with ``removed`` (bool) and ``ticker``, or ``None`` on error.
    """
    url = f"{API_BASE_URL}/etf/ticker/{ticker.strip().upper()}"
    try:
        resp = requests.delete(url, timeout=_ADMIN_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.error("DELETE /etf/ticker/%s failed: %s", ticker, exc)
        return None


def get_index_stocks(
    group: str,
    max_n: int = 100,
    period_type: str = "quarterly",
    min_gross_margin=None,
    min_roic=None,
    min_fcf_margin=None,
    min_interest_coverage=None,
    max_pe=None,
    min_score=None,
    hide_na: bool = False,
) -> dict | None:
    """Fetch fundamental screener rows for top-N stocks in an index group."""
    params = {k: v for k, v in {
        "group": group,
        "max_n": max_n,
        "period_type": period_type,
        "min_gross_margin": min_gross_margin,
        "min_roic": min_roic,
        "min_fcf_margin": min_fcf_margin,
        "min_interest_coverage": min_interest_coverage,
        "max_pe": max_pe,
        "min_score": min_score,
        "hide_na": hide_na,
    }.items() if v is not None and v is not False}
    return _get("/etf/index_stocks", params=params)


# ---------------------------------------------------------------------------
# Zombies
# ---------------------------------------------------------------------------

def get_zombies(search=None, sector=None, page=1, page_size=50) -> dict | None:
    """Fetch the zombie kill list."""
    params = {k: v for k, v in {
        "search": search,
        "sector": sector,
        "page": page,
        "page_size": page_size,
    }.items() if v is not None}
    return _get("/zombies", params=params)


# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------

def compare_tickers(
    tickers: list[str],
    min_gross_margin=None,
    min_roic=None,
    min_fcf_margin=None,
    min_interest_coverage=None,
    max_pe=None,
) -> dict | None:
    """Run side-by-side comparison for a list of tickers."""
    body = {
        "tickers": tickers,
        "min_gross_margin": min_gross_margin,
        "min_roic": min_roic,
        "min_fcf_margin": min_fcf_margin,
        "min_interest_coverage": min_interest_coverage,
        "max_pe": max_pe,
    }
    return _post("/compare", body)


# ---------------------------------------------------------------------------
# Retirement
# ---------------------------------------------------------------------------

def run_retirement(
    current_value: float,
    current_age: int,
    retirement_age: int,
    annual_contribution: float = 0.0,
    contribution_growth_rate: float = 0.03,
    target_retirement_value: float | None = None,
    inflation_rate: float = 0.03,
    n_simulations: int = 1000,
    # Planning engine parameters
    monthly_spending: float = 0.0,
    life_expectancy: int = 90,
    monthly_taxable_contribution: float = 0.0,
    trad_401k_balance: float = 0.0,
    roth_401k_balance: float = 0.0,
    monthly_trad_401k: float = 0.0,
    monthly_roth_401k: float = 0.0,
    employer_match_rate: float = 0.0,
    employer_match_cap: float = 0.06,
    annual_salary: float = 0.0,
    irs_limit_401k: float = 23_500.0,
    # Roth IRA
    roth_ira_balance: float = 0.0,
    monthly_roth_ira: float = 0.0,
    irs_limit_roth_ira: float = 7_000.0,
    # Tax rates
    ordinary_income_rate: float = 0.22,
    capital_gains_rate: float = 0.15,
    cost_basis_ratio: float = 0.5,
    post_retirement_return: float = 0.05,
    use_cached_randoms: bool = True,
    run_mc: bool = True,
) -> dict | None:
    """Run a retirement projection (planning + optional Monte Carlo)."""
    body = {
        "current_value": current_value,
        "current_age": current_age,
        "retirement_age": retirement_age,
        "annual_contribution": annual_contribution,
        "contribution_growth_rate": contribution_growth_rate,
        "target_retirement_value": target_retirement_value,
        "inflation_rate": inflation_rate,
        "n_simulations": n_simulations,
        "monthly_spending": monthly_spending,
        "life_expectancy": life_expectancy,
        "monthly_taxable_contribution": monthly_taxable_contribution,
        "trad_401k_balance": trad_401k_balance,
        "roth_401k_balance": roth_401k_balance,
        "monthly_trad_401k": monthly_trad_401k,
        "monthly_roth_401k": monthly_roth_401k,
        "employer_match_rate": employer_match_rate,
        "employer_match_cap": employer_match_cap,
        "annual_salary": annual_salary,
        "irs_limit_401k": irs_limit_401k,
        "roth_ira_balance": roth_ira_balance,
        "monthly_roth_ira": monthly_roth_ira,
        "irs_limit_roth_ira": irs_limit_roth_ira,
        "ordinary_income_rate": ordinary_income_rate,
        "capital_gains_rate": capital_gains_rate,
        "cost_basis_ratio": cost_basis_ratio,
        "post_retirement_return": post_retirement_return,
        "use_cached_randoms": use_cached_randoms,
        "run_mc": run_mc,
    }
    return _post("/retirement", body, timeout=_RETIREMENT_TIMEOUT)


# ---------------------------------------------------------------------------
# Metals
# ---------------------------------------------------------------------------

def get_metals() -> dict | None:
    """Fetch current metals spot prices."""
    return _get("/metals")


def get_metal_history(metal_id: str, days: int = 365) -> list | None:
    """Fetch price history for a single metal."""
    return _get(f"/metals/{metal_id}/history", params={"days": days})


def get_metal_inventory_history(metal_id: str, days: int = 1825) -> list | None:
    """Fetch ETF-holdings inventory history for gold or silver."""
    return _get(f"/metals/{metal_id}/inventory", params={"days": days})


def get_metal_stack(user_id: str = "default") -> dict | None:
    """Fetch personal metal stack summary."""
    return _get("/metals/stack/summary", params={"user_id": user_id})


def add_stack_transaction(
    metal: str,
    oz: float,
    price_per_oz: float,
    transaction_date: str,
    note: str = "",
    user_id: str = "default",
) -> dict | None:
    """Post a new metal stack transaction."""
    return _post(
        f"/metals/stack/transaction?user_id={user_id}",
        {"metal": metal, "oz": oz, "price_per_oz": price_per_oz,
         "transaction_date": transaction_date, "note": note},
    )


# ---------------------------------------------------------------------------
# Macro
# ---------------------------------------------------------------------------

def get_macro_latest() -> list | None:
    """Fetch latest values for all FRED series."""
    return _get("/macro")


def get_macro_series(series_id: str, days: int = 1825) -> dict | None:
    """Fetch time-series for a single FRED series."""
    return _get(f"/macro/{series_id}", params={"days": days})


# ---------------------------------------------------------------------------
# Sentiment, News, Disasters, Calendar
# ---------------------------------------------------------------------------

def get_sentiment_latest() -> dict | None:
    """Fetch the latest composite sentiment snapshot."""
    return _get("/sentiment/latest")


def get_sentiment_history(days: int = 90) -> list | None:
    """Fetch daily sentiment time-series."""
    return _get("/sentiment/history", params={"days": days})


def refresh_sentiment() -> dict | None:
    """Trigger a live sentiment refresh (yfinance VIX/P-C fetch)."""
    return _post("/sentiment/refresh", {})


def get_news(category: str | None = None, hours: int = 48, limit: int = 50) -> list | None:
    """Fetch recent news articles."""
    params: dict = {"hours": hours, "limit": limit}
    if category:
        params["category"] = category
    return _get("/news", params=params)


def get_news_for_ticker(ticker: str, hours: int = 48) -> list | None:
    """Fetch news articles mentioning a specific ticker."""
    return _get(f"/news/{ticker.upper()}", params={"hours": hours})


def refresh_news() -> dict | None:
    """Trigger a NewsAPI fetch (requires NEWSAPI_KEY)."""
    return _post("/news/refresh", {})


def get_earthquakes(days: int = 7, min_magnitude: float = 5.5) -> list | None:
    """Fetch recent earthquake events."""
    return _get("/disasters/earthquakes", params={"days": days, "min_magnitude": min_magnitude})


def refresh_earthquakes() -> dict | None:
    """Trigger a USGS earthquake feed refresh."""
    return _post("/disasters/refresh", {})


def get_calendar(days: int = 30, event_type: str | None = None) -> list | None:
    """Fetch upcoming economic calendar events."""
    params: dict = {"days": days}
    if event_type:
        params["event_type"] = event_type
    return _get("/calendar", params=params)


def seed_calendar() -> dict | None:
    """Seed the calendar with FOMC / CPI / NFP dates."""
    return _post("/calendar/seed", {})


def get_geopolitical_events(
    days: int = 7,
    country_code: str | None = None,
    event_type: str | None = None,
    quad_class: int | None = None,
    limit: int = 100,
) -> list | None:
    """Fetch recent GDELT geopolitical events."""
    params: dict = {"days": days, "limit": limit}
    if country_code:
        params["country_code"] = country_code
    if event_type:
        params["event_type"] = event_type
    if quad_class is not None:
        params["quad_class"] = quad_class
    return _get("/geopolitical/events", params=params)


def get_goldstein_trend(days: int = 30) -> list | None:
    """Fetch daily average Goldstein score trend."""
    return _get("/geopolitical/trend", params={"days": days})


def refresh_geopolitical() -> dict | None:
    """Trigger a GDELT fetch and store significant events."""
    return _post("/geopolitical/refresh", {})


def get_liquidity(days: int = 1825) -> dict | None:
    """Fetch Net Liquidity time-series and QE/QT regime.

    Returns
    -------
    dict with keys:
        ``regime`` ("QE", "QT", "NEUTRAL") and
        ``data`` (list of {date, walcl, rrpontsyd, wdtgal, net_liquidity}).
    """
    return _get("/liquidity", params={"days": days})


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

def admin_fetch(tickers: list[str], period_type: str = "both") -> dict | None:
    """Trigger data fetch for a list of tickers."""
    return _post("/admin/fetch", {"tickers": tickers, "period_type": period_type},
                 timeout=_ADMIN_TIMEOUT)


def admin_compute(tickers: list[str] | None = None) -> dict | None:
    """Trigger metric recomputation.

    Parameters
    ----------
    tickers : list[str] | None
        Restrict recomputation to these tickers.  ``None`` recomputes all.
    """
    body = {"tickers": tickers} if tickers else {}
    return _post("/admin/compute", body, timeout=_ADMIN_TIMEOUT)


def admin_classify(tickers: list[str] | None = None) -> dict | None:
    """Trigger zombie reclassification.

    Parameters
    ----------
    tickers : list[str] | None
        Restrict classification to these tickers.  ``None`` classifies all.
    """
    body = {"tickers": tickers} if tickers else {}
    return _post("/admin/classify", body, timeout=_ADMIN_TIMEOUT)


def admin_refresh_macro() -> dict:
    """Trigger FRED macro data refresh.

    Returns a dict with keys ``results`` (on success) or ``error`` (on failure).
    Never returns None so callers can always inspect the result.
    """
    url = f"{API_BASE_URL}/admin/refresh/macro"
    try:
        resp = requests.post(url, json={}, timeout=_ADMIN_TIMEOUT)
        if not resp.ok:
            detail = resp.json().get("detail", resp.text) if resp.content else resp.reason
            return {"error": detail}
        return resp.json()
    except requests.exceptions.Timeout:
        return {"error": "Request timed out — FRED fetch is taking too long. Try again shortly."}
    except Exception as exc:
        logger.error("POST /admin/refresh/macro failed: %s", exc)
        return {"error": str(exc)}


def admin_refresh_metals() -> dict | None:
    return _post("/admin/refresh/metals", {})


def admin_refresh_comex() -> dict | None:
    """Trigger GLD/SLV ETF inventory fetch (COMEX proxy)."""
    return _post("/admin/refresh/comex", {}, timeout=_ADMIN_TIMEOUT)


def admin_list_tickers() -> list | None:
    return _get("/admin/tickers")


def admin_delete_ticker(ticker: str) -> dict | None:
    """Remove a ticker and all its associated data from the database."""
    url = f"{API_BASE_URL}/admin/ticker/{ticker.upper()}"
    try:
        resp = requests.delete(url, timeout=_ADMIN_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.error("DELETE /admin/ticker/%s failed: %s", ticker, exc)
        return None


def delete_stack_transaction(tx_index: int, user_id: str = "default") -> dict | None:
    """Remove a metal stack transaction by its 0-based index."""
    url = f"{API_BASE_URL}/metals/stack/transaction/{tx_index}"
    try:
        resp = requests.delete(url, params={"user_id": user_id}, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.error("DELETE /metals/stack/transaction/%d failed: %s", tx_index, exc)
        return None


# ---------------------------------------------------------------------------
# Daily Strategy Scanner
# ---------------------------------------------------------------------------

_SCANNER_TIMEOUT = 30   # seconds for scanner API calls


def scanner_get_status(job_id: int | None = None) -> dict | None:
    """Return scan status for the latest job, or a specific job by ID."""
    params = {"job_id": job_id} if job_id is not None else None
    return _get("/api/scanner/status", params=params)


def scanner_get_results(scan_date: str | None = None) -> dict | None:
    """Return signal results for the latest (or a given) completed scan.

    Parameters
    ----------
    scan_date:
        ISO date string (YYYY-MM-DD).  ``None`` = latest completed scan.
    """
    params = {"scan_date": scan_date} if scan_date else None
    return _get("/api/scanner/results", params=params)


def scanner_trigger(
    strategy_slugs: list[str] | None = None,
    etf_tickers: list[str] | None = None,
    force: bool = False,
) -> dict | None:
    """Manually trigger a daily strategy scan.

    Parameters
    ----------
    force:
        When ``True``, forces a full recompute even if a completed scan already
        exists for today.  The existing results are replaced.

    Returns ``None`` if the request fails (e.g. a scan is already running).
    """
    payload: dict = {}
    if strategy_slugs is not None:
        payload["strategy_slugs"] = strategy_slugs
    if etf_tickers is not None:
        payload["etf_tickers"] = etf_tickers
    if force:
        payload["force"] = True
    return _post("/api/scanner/trigger", payload, timeout=_SCANNER_TIMEOUT)


def scanner_get_backtest(
    ticker: str,
    strategy: str,
    scan_date: str | None = None,
) -> dict | None:
    """Return the stored backtest summary for a ticker × strategy pair."""
    params: dict = {"ticker": ticker, "strategy": strategy}
    if scan_date:
        params["scan_date"] = scan_date
    return _get("/api/scanner/backtest", params=params)


def scanner_get_universe() -> dict | None:
    """Return the current universe snapshot (cached or freshly resolved)."""
    return _get("/api/scanner/universe")


# ---------------------------------------------------------------------------
# Trade Tracker
# ---------------------------------------------------------------------------

def trades_list(
    status: str | None = None,
    ticker: str | None = None,
    strategy: str | None = None,
) -> dict | None:
    """Return list of tracked trades."""
    params = {k: v for k, v in {
        "status": status,
        "ticker": ticker,
        "strategy": strategy,
    }.items() if v is not None}
    return _get("/api/trades/", params=params)


def trades_create(payload: dict) -> dict | None:
    """Create a new tracked trade."""
    return _post("/api/trades/", payload)


def trades_update(trade_id: int, payload: dict) -> dict | None:
    """Update editable fields on a trade via PATCH."""
    url = f"{API_BASE_URL}/api/trades/{trade_id}"
    try:
        resp = requests.patch(url, json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.error("PATCH /api/trades/%s failed: %s", trade_id, exc)
        return None


def trades_delete(trade_id: int) -> bool:
    """Delete a trade. Returns True on success."""
    url = f"{API_BASE_URL}/api/trades/{trade_id}"
    try:
        resp = requests.delete(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.error("DELETE /api/trades/%s failed: %s", trade_id, exc)
        return False


def trades_check(scan_signal_id: int) -> dict | None:
    """Check whether a scanner signal is already tracked."""
    return _get("/api/trades/check", params={"scan_signal_id": scan_signal_id})


def trades_import(rows: list[dict]) -> dict | None:
    """Bulk-import trade rows."""
    return _post("/api/trades/import", rows)

