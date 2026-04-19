"""
src.api.schemas
===============
Pydantic request and response models used by the FastAPI routers.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Common
# ---------------------------------------------------------------------------

class PaginatedMeta(BaseModel):
    """Pagination metadata included in list responses.

    Attributes
    ----------
    page : int
    page_size : int
    total : int
    total_pages : int
    """
    page: int
    page_size: int
    total: int
    total_pages: int


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class MarketCard(BaseModel):
    label: str
    value: float | None = None
    change_pct: float | None = None
    unit: str = ""


class MacroValue(BaseModel):
    series_id: str
    name: str
    value: float | None = None
    obs_date: date | None = None


class MetalPrice(BaseModel):
    metal: str
    price: float | None = None
    obs_date: date | None = None


class DashboardResponse(BaseModel):
    screened_count: int
    zombie_count: int
    quality_count: int
    market_cards: list[MarketCard]
    macro_values: list[MacroValue]
    metal_prices: list[MetalPrice]
    gold_silver_ratio: float | None = None


# ---------------------------------------------------------------------------
# Screener
# ---------------------------------------------------------------------------

class ScreenerRow(BaseModel):
    ticker: str
    name: str | None = None
    sector: str | None = None
    industry: str | None = None
    description: str = ""
    period_end: str | None = None
    gross_margin: float | None = None
    roic: float | None = None
    fcf_margin: float | None = None
    interest_coverage: float | None = None
    pe_ratio: float | None = None
    current_price: float | None = None
    market_cap: float | None = None
    # Extended value / quality metrics
    quality_score: float | None = None
    current_ratio: float | None = None
    pb_ratio: float | None = None
    pe_x_pb: float | None = None          # P/E × P/B; ≤ 22.5 satisfies Graham criterion
    graham_number: float | None = None    # sqrt(22.5 × EPS × BVPS) — Graham upper price bound
    ncav_per_share: float | None = None
    net_net_flag: bool | None = None      # True if price ≤ 2/3 × NCAV/share
    ltd_lte_nca: bool | None = None       # True if long-term debt ≤ net current assets
    roe: float | None = None
    owner_earnings_per_share: float | None = None
    roe_leveraged: bool | None = None     # True if ROE > 15% but D/E > 2 (leverage-inflated)
    # Pass/fail flags for colour coding
    gm_pass: bool = True
    roic_pass: bool = True
    fcf_pass: bool = True
    ic_pass: bool = True
    pe_pass: bool = True


class ScreenerResponse(BaseModel):
    rows: list[ScreenerRow]
    meta: PaginatedMeta


class IndexStocksResponse(BaseModel):
    """Response for index-constituent stock fundamentals."""
    rows: list[ScreenerRow]
    total_constituents: int
    loaded: int
    missing_tickers: list[str]


class PresetThresholds(BaseModel):
    name: str
    label: str
    min_gross_margin: float | None = None
    min_roic: float | None = None
    min_fcf_margin: float | None = None
    min_interest_coverage: float | None = None
    max_pe: float | None = None


# ---------------------------------------------------------------------------
# Zombies
# ---------------------------------------------------------------------------

class ZombieRow(BaseModel):
    ticker: str
    name: str | None = None
    sector: str | None = None
    industry: str | None = None
    severity: float | None = None
    asof_date: str | None = None
    reasons: list[str] = Field(default_factory=list)
    gross_margin: float | None = None
    roic: float | None = None
    fcf_margin: float | None = None
    interest_coverage: float | None = None
    pe_ratio: float | None = None


class ZombieResponse(BaseModel):
    rows: list[ZombieRow]
    meta: PaginatedMeta


# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------

class CompareRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1, max_length=50)
    min_gross_margin: float | None = None
    min_roic: float | None = None
    min_fcf_margin: float | None = None
    min_interest_coverage: float | None = None
    max_pe: float | None = None


class CompareCell(BaseModel):
    value: float | None = None
    band: str = "neutral"   # "good", "neutral", "bad"


class CompareRow(BaseModel):
    ticker: str
    name: str | None = None
    sector: str | None = None
    gross_margin: CompareCell
    roic: CompareCell
    fcf_margin: CompareCell
    interest_coverage: CompareCell
    pe_ratio: CompareCell
    overall_score: float | None = None
    is_zombie: bool = False


class CompareResponse(BaseModel):
    rows: list[CompareRow]
    thresholds: dict[str, float | None]


# ---------------------------------------------------------------------------
# Retirement
# ---------------------------------------------------------------------------

class RetirementRequest(BaseModel):
    # ---- Monte Carlo (existing) ----
    current_value: float = Field(..., gt=0, description="Taxable account balance ($)")
    current_age: int = Field(..., ge=18, le=90)
    retirement_age: int = Field(..., ge=19, le=100)
    annual_contribution: float = Field(default=0.0, ge=0)
    contribution_growth_rate: float = Field(default=0.03, ge=0, le=1)
    target_retirement_value: float | None = None
    inflation_rate: float = Field(default=0.03, ge=0, le=0.20)
    n_simulations: int = Field(default=1000, ge=100, le=10000)

    # ---- Planning engine: personal ----
    monthly_spending: float = Field(default=0.0, ge=0,
        description="Current monthly spending in today's dollars; 0 = skip planning")
    life_expectancy: int = Field(default=90, ge=50, le=120)

    # ---- Planning engine: taxable account ----
    monthly_taxable_contribution: float = Field(default=0.0, ge=0)

    # ---- Planning engine: 401k balances ----
    trad_401k_balance: float = Field(default=0.0, ge=0)
    roth_401k_balance: float = Field(default=0.0, ge=0)

    # ---- Planning engine: 401k contributions ----
    monthly_trad_401k: float = Field(default=0.0, ge=0)
    monthly_roth_401k: float = Field(default=0.0, ge=0)
    employer_match_rate: float = Field(default=0.0, ge=0, le=2.0,
        description="Employer match rate as decimal (e.g. 0.80 = 80%)")
    employer_match_cap: float = Field(default=0.06, ge=0, le=1.0,
        description="Match cap as fraction of salary (e.g. 0.06 = 6%)")
    annual_salary: float = Field(default=0.0, ge=0)
    irs_limit_401k: float = Field(default=23_500.0, gt=0)

    # ---- Planning engine: tax rates ----
    ordinary_income_rate: float = Field(default=0.22, ge=0, le=1.0)
    capital_gains_rate: float = Field(default=0.15, ge=0, le=1.0)
    cost_basis_ratio: float = Field(default=0.5, ge=0, le=1.0,
        description="Fraction of taxable FV that is cost basis (not taxed)")

    # ---- Planning engine: Roth IRA ----
    roth_ira_balance: float = Field(default=0.0, ge=0)
    monthly_roth_ira: float = Field(default=0.0, ge=0)
    irs_limit_roth_ira: float = Field(default=7_000.0, gt=0,
        description="2025 IRS Roth IRA annual contribution limit")

    # ---- Planning engine: post-retirement ----
    post_retirement_return: float = Field(default=0.05, ge=0, le=0.30)

    # ---- Simulation mode ----
    use_cached_randoms: bool = Field(default=True, description="Use pre-computed randoms for speed")

    # ---- Run control ----
    run_mc: bool = Field(default=True,
        description="Set False to skip Monte Carlo (planning-only, faster)")


class YearProjectionSchema(BaseModel):
    age: int
    year_offset: int
    p10: float
    p50: float
    p90: float
    mean: float


class ScenarioResultSchema(BaseModel):
    label: str
    projections: list[YearProjectionSchema]
    final_p10: float
    final_p50: float
    final_p90: float
    readiness_score: float | None = None


class PlanningResultSchema(BaseModel):
    """Deterministic planning engine output."""
    monthly_spending_at_retirement: float
    required_nest_egg: float
    required_return_rate: float
    fv_taxable: float
    fv_trad_401k: float
    fv_roth_401k: float
    fv_roth_ira: float
    after_tax_total: float
    eff_monthly_trad: float
    eff_monthly_roth: float
    eff_monthly_match: float
    eff_monthly_roth_ira: float


class RetirementResponse(BaseModel):
    scenarios: dict[str, ScenarioResultSchema]
    horizon_years: int
    total_portfolio_value: float = 0.0
    planning: PlanningResultSchema | None = None


# ---------------------------------------------------------------------------
# Metals
# ---------------------------------------------------------------------------

class MetalsHistoryPoint(BaseModel):
    date: date
    price: float


class MetalsDetailResponse(BaseModel):
    current_prices: dict[str, dict]
    gold_silver_ratio: float | None = None


class StackTransaction(BaseModel):
    metal: str
    oz: float = Field(..., gt=0)
    price_per_oz: float = Field(..., gt=0)
    transaction_date: date
    note: str = ""


# ---------------------------------------------------------------------------
# Macro
# ---------------------------------------------------------------------------

class MacroSeriesPoint(BaseModel):
    date: date
    value: float


class MacroSeriesResponse(BaseModel):
    series_id: str
    name: str
    data: list[MacroSeriesPoint]


# ---------------------------------------------------------------------------
# ETF Screener
# ---------------------------------------------------------------------------

class ETFRow(BaseModel):
    """One row in the ETF screener grid."""
    ticker: str
    name: str | None = None
    category: str | None = None
    description: str = ""
    expense_ratio: float | None = None       # % (e.g. 0.09 for 0.09%)
    aum_b: float | None = None               # total assets in billions USD
    pe_ratio: float | None = None
    dividend_yield: float | None = None      # % (e.g. 1.5 for 1.5%)
    three_month_return: float | None = None  # % trailing 3-month return
    six_month_return: float | None = None    # % trailing 6-month return
    one_yr_return: float | None = None       # % trailing 1-year total return
    three_yr_return: float | None = None     # % 3-year avg annual return
    # Pass/fail flags for colour coding
    er_pass: bool = True
    aum_pass: bool = True
    pe_pass: bool = True
    dy_pass: bool = True
    r3m_pass: bool = True
    r6m_pass: bool = True
    r1_pass: bool = True
    r3_pass: bool = True


class ETFScreenerResponse(BaseModel):
    rows: list[ETFRow]
    total: int


class ETFPreset(BaseModel):
    name: str
    label: str
    max_expense_ratio: float | None = None
    min_dividend_yield: float | None = None
    min_one_yr_return: float | None = None
    min_three_yr_return: float | None = None
    min_aum_b: float | None = None
    max_pe: float | None = None


# ---------------------------------------------------------------------------
# News & Sentiment
# ---------------------------------------------------------------------------

class NewsArticleOut(BaseModel):
    id: int
    headline: str
    source: str | None = None
    url: str
    published_at: Any  # datetime serialised as string
    category: str | None = None
    sentiment_score: float | None = None
    sentiment_label: str | None = None
    related_tickers: str | None = None


class EarthquakeEventOut(BaseModel):
    id: int
    event_time: Any  # datetime serialised as string
    magnitude: float
    depth_km: float | None = None
    location: str
    lat: float | None = None
    lon: float | None = None
    economic_zone_flag: bool | None = None


class GeopoliticalEventOut(BaseModel):
    id: int
    gdelt_event_id: int
    event_date: date
    actor1: str | None = None
    actor2: str | None = None
    goldstein_scale: float | None = None
    event_type: str | None = None
    quad_class: int | None = None
    country_code: str | None = None
    lat: float | None = None
    lon: float | None = None
    source_url: str | None = None
    num_mentions: int | None = None
    avg_tone: float | None = None


class SentimentLatestOut(BaseModel):
    snapshot_date: date | None = None
    fear_greed_score: float | None = None
    put_call_ratio: float | None = None
    vix_value: float | None = None
    vix_percentile: float | None = None


class CalendarEventOut(BaseModel):
    id: int
    event_date: date
    event_name: str
    event_type: str | None = None
    importance: str | None = None
    actual: str | None = None
    forecast: str | None = None
    previous: str | None = None


# ---------------------------------------------------------------------------
# Liquidity
# ---------------------------------------------------------------------------

class LiquidityPoint(BaseModel):
    date: date
    walcl: float
    rrpontsyd: float
    wdtgal: float
    net_liquidity: float


class LiquidityResponse(BaseModel):
    regime: str          # "QE", "QT", or "NEUTRAL"
    data: list[LiquidityPoint]


# ---------------------------------------------------------------------------
# Ingestion / Admin
# ---------------------------------------------------------------------------

class FetchRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1)
    period_type: str = "both"  # "annual", "quarterly", or "both"


class ComputeRequest(BaseModel):
    tickers: list[str] | None = None  # None = recompute all tickers in DB


class FetchResponse(BaseModel):
    results: dict[str, Any]
    message: str = ""


# ---------------------------------------------------------------------------
# Daily Strategy Scanner
# ---------------------------------------------------------------------------

class ScanTriggerRequest(BaseModel):
    """Request body for POST /api/scanner/trigger."""
    strategy_slugs: list[str] | None = None  # None = all built-in strategies
    etf_tickers: list[str] | None = None     # None = default ETF universe
    force: bool = False                       # True = recompute even if completed scan exists


class ScanTriggerResponse(BaseModel):
    """Response for POST /api/scanner/trigger."""
    job_id: int
    message: str = ""
    was_reused: bool = False   # True when an existing completed scan was returned without re-running


class ScanStatusResponse(BaseModel):
    """Response for GET /api/scanner/status."""
    id: int
    scan_date: str
    status: str
    trigger_type: str
    ticker_count: int
    signal_count: int
    started_at: str | None
    completed_at: str | None
    error_message: str | None
    strategies: list[str]
    universe_etfs: list[str]
    is_running: bool = False


class ScanSignalItem(BaseModel):
    """A single detected signal row."""
    ticker: str
    strategy: str
    strategy_display_name: str
    win_rate: float | None = None       # 0.0–1.0 from backtest
    trade_count: int | None = None      # completed trades in backtest
    signal_type: int          # 1 = BUY, -1 = SELL
    signal_date: str          # ISO date string
    close_price: float | None
    days_ago: int
    source_etfs: list[str]


class ScanResultsResponse(BaseModel):
    """Response for GET /api/scanner/results."""
    scan_date: str
    status: str
    job_id: int
    latest_buys:  list[ScanSignalItem]
    latest_sells: list[ScanSignalItem]
    past_buys:    list[ScanSignalItem]
    past_sells:   list[ScanSignalItem]
    latest_trading_date: str | None = None


class ScanBacktestItem(BaseModel):
    """Backtest summary for one ticker × strategy pair."""
    ticker: str
    strategy: str
    strategy_display_name: str
    trade_count: int
    win_rate: float
    total_pnl: float
    avg_pnl: float
    trades: list[dict]
    data_start_date: str | None
    data_end_date: str | None
    bar_count: int | None


class ScanUniverseResponse(BaseModel):
    """Response for GET /api/scanner/universe."""
    source_etfs: list[str]
    ticker_count: int
    resolved_at: str
    tickers: list[str]
