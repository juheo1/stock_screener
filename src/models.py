"""
src.models
==========
SQLAlchemy ORM models for every table in the stock screener database.

Table summary
-------------
equities             -- Master list of tracked tickers with metadata.
statements_income    -- Annual / quarterly income-statement rows.
statements_balance   -- Annual / quarterly balance-sheet rows.
statements_cashflow  -- Annual / quarterly cash-flow rows.
metrics_quarterly    -- Pre-computed derived metrics (gross margin, ROIC …).
flags                -- Zombie-detection flags and reasons per ticker/date.
macro_series         -- FRED macro time-series (M2, reverse repo …).
metals_series        -- Metals spot prices (gold, silver …).
user_portfolios      -- Saved user portfolios and settings (JSON blobs).
user_metal_stack     -- Personal precious-metal stack transactions (JSON).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from src.database import Base


# ---------------------------------------------------------------------------
# Equities
# ---------------------------------------------------------------------------

class Equity(Base):
    """Master row for a single publicly-traded ticker.

    Columns
    -------
    ticker      Primary key symbol (e.g. ``AAPL``).
    name        Full company name.
    exchange    Exchange code (NASDAQ, NYSE …).
    sector      GICS sector string.
    industry    GICS industry string.
    currency    Reporting currency (USD, EUR …).
    updated_at  Timestamp of last metadata refresh.
    """

    __tablename__ = "equities"

    ticker = Column(String(20), primary_key=True)
    name = Column(String(256))
    exchange = Column(String(64))
    sector = Column(String(128))
    industry = Column(String(128))
    currency = Column(String(8), default="USD")
    description = Column(Text, default="")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ---------------------------------------------------------------------------
# Financial Statements
# ---------------------------------------------------------------------------

class StatementIncome(Base):
    """One row = one reporting period for the income statement.

    Columns
    -------
    id                  Surrogate primary key.
    ticker              Foreign key to :class:`Equity`.
    period_end          Statement period-end date.
    period_type         ``annual`` or ``quarterly``.
    revenue             Total revenue.
    cost_of_revenue     Cost of goods sold / services.
    gross_profit        Revenue minus cost of revenue.
    operating_income    EBIT / operating profit.
    interest_expense    Interest expense (positive = expense).
    income_tax_expense  Income taxes paid / accrued.
    net_income          Bottom-line net income.
    diluted_eps         Diluted earnings per share.
    diluted_shares      Diluted weighted-average shares outstanding.
    """

    __tablename__ = "statements_income"
    __table_args__ = (
        UniqueConstraint("ticker", "period_end", "period_type", name="uq_income"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), ForeignKey("equities.ticker"), nullable=False, index=True)
    period_end = Column(Date, nullable=False)
    period_type = Column(String(16), nullable=False, default="annual")  # annual | quarterly

    revenue = Column(Float)
    cost_of_revenue = Column(Float)
    gross_profit = Column(Float)
    operating_income = Column(Float)
    interest_expense = Column(Float)
    income_tax_expense = Column(Float)
    net_income = Column(Float)
    diluted_eps = Column(Float)
    diluted_shares = Column(Float)


class StatementBalance(Base):
    """One row = one reporting period for the balance sheet.

    Columns
    -------
    id                  Surrogate primary key.
    ticker              Foreign key to :class:`Equity`.
    period_end          Statement period-end date.
    period_type         ``annual`` or ``quarterly``.
    total_assets        Total assets.
    total_liabilities   Total liabilities (net minority interest).
    total_equity        Total stockholders' equity.
    cash                Cash and cash equivalents.
    short_term_debt     Short-term / current portion of debt.
    long_term_debt      Long-term debt.
    total_debt          total short-term + long-term debt.
    working_capital     Current assets minus current liabilities.
    """

    __tablename__ = "statements_balance"
    __table_args__ = (
        UniqueConstraint("ticker", "period_end", "period_type", name="uq_balance"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), ForeignKey("equities.ticker"), nullable=False, index=True)
    period_end = Column(Date, nullable=False)
    period_type = Column(String(16), nullable=False, default="annual")

    total_assets = Column(Float)
    total_liabilities = Column(Float)
    total_equity = Column(Float)
    cash = Column(Float)
    short_term_debt = Column(Float)
    long_term_debt = Column(Float)
    total_debt = Column(Float)
    working_capital = Column(Float)
    current_assets = Column(Float)
    current_liabilities = Column(Float)


class StatementCashflow(Base):
    """One row = one reporting period for the cash-flow statement.

    Columns
    -------
    id                      Surrogate primary key.
    ticker                  Foreign key to :class:`Equity`.
    period_end              Statement period-end date.
    period_type             ``annual`` or ``quarterly``.
    operating_cashflow      Cash from operating activities.
    capex                   Capital expenditures (stored as negative convention).
    free_cashflow           operating_cashflow + capex (FCF).
    investing_cashflow      Cash from investing activities.
    financing_cashflow      Cash from financing activities.
    """

    __tablename__ = "statements_cashflow"
    __table_args__ = (
        UniqueConstraint("ticker", "period_end", "period_type", name="uq_cashflow"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), ForeignKey("equities.ticker"), nullable=False, index=True)
    period_end = Column(Date, nullable=False)
    period_type = Column(String(16), nullable=False, default="annual")

    operating_cashflow = Column(Float)
    capex = Column(Float)
    free_cashflow = Column(Float)
    investing_cashflow = Column(Float)
    financing_cashflow = Column(Float)
    depreciation_amortization = Column(Float)


# ---------------------------------------------------------------------------
# Computed Metrics
# ---------------------------------------------------------------------------

class MetricsQuarterly(Base):
    """Pre-computed derived metrics for one ticker and one reporting period.

    Columns
    -------
    id                  Surrogate primary key.
    ticker              Foreign key to :class:`Equity`.
    period_end          Statement period-end date.
    period_type         ``annual`` or ``quarterly``.
    asof_date           Date the metrics were computed.
    gross_margin        (Gross profit / Revenue) * 100  [%].
    roic                NOPAT / Invested capital  [ratio].
    fcf_margin          (FCF / Revenue) * 100  [%].
    interest_coverage   EBIT / Interest expense  [ratio].
    pe_ratio            Price / EPS  [ratio].
    current_price       Stock price at ``asof_date``.
    market_cap          Market capitalisation at ``asof_date``.
    """

    __tablename__ = "metrics_quarterly"
    __table_args__ = (
        UniqueConstraint("ticker", "period_end", "period_type", name="uq_metrics"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), ForeignKey("equities.ticker"), nullable=False, index=True)
    period_end = Column(Date, nullable=False)
    period_type = Column(String(16), nullable=False, default="annual")
    asof_date = Column(Date)

    gross_margin = Column(Float)
    roic = Column(Float)
    fcf_margin = Column(Float)
    interest_coverage = Column(Float)
    pe_ratio = Column(Float)

    current_price = Column(Float)
    market_cap = Column(Float)

    # Extended value / quality metrics
    current_ratio = Column(Float)        # current_assets / current_liabilities
    pb_ratio = Column(Float)             # market_cap / total_equity
    graham_number = Column(Float)        # sqrt(22.5 × EPS × BVPS); Graham upper-bound price
    ncav_per_share = Column(Float)       # (current_assets − total_liabilities) / shares
    roe = Column(Float)                  # net_income / total_equity  [ratio]
    owner_earnings_per_share = Column(Float)  # (net_income + D&A − |capex|) / shares
    quality_score = Column(Float)        # 0–100 composite band score (same as Batch Compare)


# ---------------------------------------------------------------------------
# Zombie Flags
# ---------------------------------------------------------------------------

class Flag(Base):
    """Zombie-detection flag for a ticker on a given date.

    Columns
    -------
    id              Surrogate primary key.
    ticker          Foreign key to :class:`Equity`.
    asof_date       Date the classification was run.
    is_zombie       True if the ticker meets zombie criteria.
    reasons_json    JSON array of reason strings.
    severity        0–100 severity score (higher = worse).
    """

    __tablename__ = "flags"
    __table_args__ = (
        UniqueConstraint("ticker", "asof_date", name="uq_flag"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), ForeignKey("equities.ticker"), nullable=False, index=True)
    asof_date = Column(Date, nullable=False, index=True)
    is_zombie = Column(Boolean, nullable=False, default=False)
    reasons_json = Column(Text, default="[]")
    severity = Column(Float, default=0.0)


# ---------------------------------------------------------------------------
# Macro Series
# ---------------------------------------------------------------------------

class MacroSeries(Base):
    """One row = one observation for a FRED macro series.

    Columns
    -------
    id          Surrogate primary key.
    series_id   FRED series code (e.g. ``M2SL``).
    series_name Human-readable name.
    obs_date    Observation date.
    value       Series value.
    """

    __tablename__ = "macro_series"
    __table_args__ = (
        UniqueConstraint("series_id", "obs_date", name="uq_macro"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    series_id = Column(String(32), nullable=False, index=True)
    series_name = Column(String(128))
    obs_date = Column(Date, nullable=False, index=True)
    value = Column(Float)


# ---------------------------------------------------------------------------
# Metals Series
# ---------------------------------------------------------------------------

class MetalsSeries(Base):
    """One row = one daily observation for a precious / industrial metal.

    Columns
    -------
    id                  Surrogate primary key.
    metal_id            Short code: gold, silver, platinum, palladium, copper.
    obs_date            Observation date.
    spot_price          Spot / futures settle price in USD.
    inventory_oz        COMEX warehouse inventory in troy oz (if available).
    """

    __tablename__ = "metals_series"
    __table_args__ = (
        UniqueConstraint("metal_id", "obs_date", name="uq_metals"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    metal_id = Column(String(16), nullable=False, index=True)
    obs_date = Column(Date, nullable=False, index=True)
    spot_price = Column(Float)
    inventory_oz = Column(Float)


# ---------------------------------------------------------------------------
# User Data
# ---------------------------------------------------------------------------

class UserPortfolio(Base):
    """Stored user portfolio and screen settings.

    Columns
    -------
    id              Surrogate primary key.
    user_id         Arbitrary user identifier string.
    portfolio_json  JSON blob: list of {ticker, shares, cost_basis} dicts.
    settings_json   JSON blob: saved screen thresholds and preferences.
    updated_at      Last modified timestamp.
    """

    __tablename__ = "user_portfolios"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, unique=True, index=True)
    portfolio_json = Column(Text, default="[]")
    settings_json = Column(Text, default="{}")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ---------------------------------------------------------------------------
# News & Sentiment
# ---------------------------------------------------------------------------

class NewsArticle(Base):
    """A news article with NLP sentiment scoring.

    Columns
    -------
    id              Surrogate primary key.
    headline        Article title / headline text.
    source          Publisher name (e.g. Reuters, Bloomberg).
    url             Canonical article URL — used as dedup key.
    published_at    Publication timestamp (UTC).
    category        Topic bucket: macro, geopolitical, financial, disaster, other.
    sentiment_score VADER compound score [-1, +1].
    sentiment_label Bullish / Neutral / Bearish.
    related_tickers Comma-separated ticker symbols mentioned in the article.
    """

    __tablename__ = "news_articles"
    __table_args__ = (
        UniqueConstraint("url", name="uq_news_url"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    headline = Column(Text, nullable=False)
    source = Column(String(128))
    url = Column(String(1024), nullable=False)
    published_at = Column(DateTime, nullable=False, index=True)
    category = Column(String(64), default="other", index=True)
    sentiment_score = Column(Float)
    sentiment_label = Column(String(16))
    related_tickers = Column(String(512), default="")


class EarthquakeEvent(Base):
    """A significant earthquake event from the USGS feed (M≥5.5).

    Columns
    -------
    id                  Surrogate primary key.
    event_time          UTC datetime of the earthquake.
    magnitude           Richter / moment magnitude.
    depth_km            Hypocentre depth in kilometres.
    location            Human-readable place description from USGS.
    lat                 Latitude (decimal degrees).
    lon                 Longitude (decimal degrees).
    economic_zone_flag  True if the event is near a major economic zone.
    """

    __tablename__ = "earthquake_events"
    __table_args__ = (
        UniqueConstraint("event_time", "location", name="uq_earthquake"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_time = Column(DateTime, nullable=False, index=True)
    magnitude = Column(Float, nullable=False)
    depth_km = Column(Float)
    location = Column(String(512), nullable=False)
    lat = Column(Float)
    lon = Column(Float)
    economic_zone_flag = Column(Boolean, default=False)


class GeopoliticalEvent(Base):
    """A significant geopolitical event sourced from GDELT 2.0.

    Columns
    -------
    id              Surrogate primary key.
    gdelt_event_id  GDELT GLOBALEVENTID — globally unique, used as dedup key.
    event_date      Calendar date of the event (SQLDATE in GDELT).
    actor1          Primary actor name (country, organisation, or person).
    actor2          Secondary actor name.
    goldstein_scale Goldstein conflict/cooperation score (-10 conflict to +10 coop).
    event_type      Human-readable CAMEO root code label (e.g. "Fighting").
    quad_class      GDELT QuadClass: 1=Verbal Coop, 2=Material Coop,
                    3=Verbal Conflict, 4=Material Conflict.
    country_code    ISO 2-letter country code of the action geography.
    lat             Action geography latitude.
    lon             Action geography longitude.
    source_url      URL of a source article for the event.
    num_mentions    Number of mentions in the 15-minute GDELT window.
    avg_tone        Average news tone for articles covering this event.
    """

    __tablename__ = "geopolitical_events"
    __table_args__ = (
        UniqueConstraint("gdelt_event_id", name="uq_gdelt_event_id"),
    )

    id              = Column(Integer, primary_key=True, autoincrement=True)
    gdelt_event_id  = Column(BigInteger, nullable=False, index=True)
    event_date      = Column(Date, nullable=False, index=True)
    actor1          = Column(String(256))
    actor2          = Column(String(256))
    goldstein_scale = Column(Float)
    event_type      = Column(String(64))
    quad_class      = Column(Integer)
    country_code    = Column(String(8), index=True)
    lat             = Column(Float)
    lon             = Column(Float)
    source_url      = Column(String(1024))
    num_mentions    = Column(Integer)
    avg_tone        = Column(Float)


class SentimentDaily(Base):
    """Daily composite sentiment snapshot.

    Columns
    -------
    id                  Surrogate primary key.
    snapshot_date       Calendar date of the snapshot.
    fear_greed_score    0–100 composite score (0 = Extreme Fear, 100 = Extreme Greed).
    put_call_ratio      CBOE equity put/call ratio.
    vix_value           VIX closing value.
    vix_percentile      VIX rank vs 1-year history (0–100).
    """

    __tablename__ = "sentiment_daily"
    __table_args__ = (
        UniqueConstraint("snapshot_date", name="uq_sentiment_date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_date = Column(Date, nullable=False, index=True)
    fear_greed_score = Column(Float)
    put_call_ratio = Column(Float)
    vix_value = Column(Float)
    vix_percentile = Column(Float)


class EconomicCalendar(Base):
    """A scheduled economic event (FOMC, CPI, NFP, etc.).

    Columns
    -------
    id          Surrogate primary key.
    event_date  Scheduled release or meeting date.
    event_name  Human-readable event name (e.g. "FOMC Meeting").
    event_type  fomc | inflation | labor | pmi | other.
    importance  high | medium | low.
    actual      Actual reported value (filled in after release).
    forecast    Consensus forecast ahead of release.
    previous    Prior reading.
    """

    __tablename__ = "economic_calendar"
    __table_args__ = (
        UniqueConstraint("event_date", "event_name", name="uq_calendar_event"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_date = Column(Date, nullable=False, index=True)
    event_name = Column(String(256), nullable=False)
    event_type = Column(String(64), default="other", index=True)
    importance = Column(String(16), default="medium")
    actual = Column(String(64))
    forecast = Column(String(64))
    previous = Column(String(64))


class UserMetalStack(Base):
    """Personal precious-metal stack transaction log.

    Columns
    -------
    id                  Surrogate primary key.
    user_id             Arbitrary user identifier string.
    transactions_json   JSON array of {metal, oz, price_per_oz, date} dicts.
    updated_at          Last modified timestamp.
    """

    __tablename__ = "user_metal_stack"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, unique=True, index=True)
    transactions_json = Column(Text, default="[]")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
