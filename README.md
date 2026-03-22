# Stock Intelligence & Screener

A local web application for stock intelligence and screening, inspired by
professional financial intelligence suites. Python powers the data pipeline,
metrics engine, and REST API. A Dash web UI provides all the interactive views.

---

## Features

| Module | Description |
|--------|-------------|
| **Intelligence Hub** | Summary KPIs, market index cards, FRED macro values, metals spot prices |
| **Stock Screener** | Threshold-based filtering on 15+ metrics with presets and CSV export |
| **Stock Screener ROK** | Same screener for Korean-listed tickers (KOSPI / KOSDAQ) |
| **ETF Screener** | ETF-level metrics (AUM, expense ratio, yield, returns) and index constituent fundamentals |
| **Zombie Kill List** | Rule-based solvency-risk detector (FCF, interest coverage, margin trend) |
| **Batch Compare** | Side-by-side heatmap for up to 50 tickers with Excel export |
| **Technical Analysis** | Interactive candlestick charts with SMA, EMA, Bollinger Bands, Donchian Channel, Volume MA |
| **Retirement Planner** | Monte Carlo projection with 3 scenarios and readiness score |
| **Metals Intel** | Spot prices, price history, gold/silver ratio, personal stack tracker |
| **Macro Monitor** | FRED time-series charts (M2, reverse repo, rates, CPI, yield curve) |
| **Fed Liquidity** | Net liquidity tracker (WALCL − RRP − TGA), QE/QT regime detection, money supply growth |
| **News & Sentiment** | Market news feed with VADER NLP sentiment scoring, Fear & Greed gauge, VIX percentile, Put/Call ratio |
| **Natural Disasters** | Real-time M5.5+ earthquake tracking from USGS with economic-zone flagging |
| **Geopolitical Monitor** | GDELT 2.0 global event tracking with Goldstein scale conflict/cooperation scoring |
| **Economic Calendar** | FOMC, CPI, NFP date schedule with countdown timers |

---

## API Keys & Data Sources

The app uses several external data sources. Some require free API keys. Features
that depend on an API key will gracefully degrade (silently skip) when the key is
not configured.

| API Key | Required? | Used For | Where to Get It |
|---------|-----------|----------|-----------------|
| `FRED_API_KEY` | **Recommended** | Macro Monitor, Fed Liquidity (M2, WALCL, RRP, TGA, rates, CPI, yield curve) | Free — sign up at [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html) |
| `NEWSAPI_KEY` | Optional | News & Sentiment page — fetches market/economy headlines from 80,000+ sources | Free tier (100 req/day, 1-month history) — sign up at [newsapi.org](https://newsapi.org/register) |
| `FINNHUB_API_KEY` | Optional | Reserved for future news source expansion (Finnhub company news) | Free tier (60 req/min) — sign up at [finnhub.io](https://finnhub.io/register) |
| `ALPHAVANTAGE_API_KEY` | Optional | Reserved for future use (earnings calendar, economic indicators) | Free tier (25 req/day) — sign up at [alphavantage.co](https://www.alphavantage.co/support/#api-key) |

### Free data sources (no API key needed)

| Data | Source | Notes |
|------|--------|-------|
| Equity statements & prices | [yfinance](https://github.com/ranaroussi/yfinance) | Financial statements, live prices, technicals |
| ETF metadata & returns | yfinance | AUM, expense ratio, P/E, dividend yield, period returns |
| Metals spot prices | yfinance futures (GC=F, SI=F, PL=F, PA=F, HG=F) | Gold, silver, platinum, palladium, copper |
| VIX & Put/Call ratio | yfinance (^VIX, ^PCCE) | Market sentiment indicators |
| Earthquake data | [USGS Earthquake API](https://earthquake.usgs.gov/fdsnws/event/1/) | Real-time M5.5+ events, no key required |
| Geopolitical events | [GDELT 2.0](https://www.gdeltproject.org/) | Global event database updated every 15 min, no key required |
| Economic calendar | Hardcoded schedule | FOMC, CPI, NFP dates (2024–2026) |

---

## Project Structure

```
stock_screener/
├── src/                         # Backend Python package
│   ├── config.py                # Settings loaded from .env
│   ├── database.py              # SQLAlchemy engine, session, init + auto-migration
│   ├── models.py                # ORM table definitions (15 tables)
│   ├── metrics.py               # Metric computation (15+ metrics)
│   ├── zombie.py                # Zombie-company classifier
│   ├── retirement.py            # Monte Carlo retirement engine
│   ├── scheduler.py             # APScheduler daily refresh jobs
│   └── ingestion/
│       ├── equity.py            # yfinance financial-statement fetcher
│       ├── etf.py               # ETF metadata & live metrics fetcher
│       ├── macro.py             # FRED macro series fetcher
│       ├── metals.py            # yfinance metals price fetcher
│       ├── liquidity.py         # Net liquidity & QE/QT regime computation
│       ├── news.py              # NewsAPI article fetcher + VADER sentiment
│       ├── sentiment.py         # VIX percentile, Fear & Greed, Put/Call ratio
│       ├── disasters.py         # USGS earthquake data fetcher
│       ├── geopolitical.py      # GDELT 2.0 event fetcher & parser
│       └── calendar_events.py   # Economic calendar (FOMC/CPI/NFP schedule)
│
├── src/api/                     # FastAPI application
│   ├── main.py                  # App factory + CORS + lifecycle
│   ├── deps.py                  # Shared dependencies (DB session)
│   ├── schemas.py               # Pydantic request/response models
│   └── routers/
│       ├── dashboard.py         # GET /dashboard
│       ├── screener.py          # GET /screener, /presets, /screener/export
│       ├── etf.py               # GET /etf
│       ├── zombies.py           # GET /zombies, /zombies/export
│       ├── compare.py           # POST /compare, /compare/export.xlsx
│       ├── retirement.py        # POST /retirement
│       ├── metals.py            # GET /metals, /metals/{id}/history, stack endpoints
│       ├── macro.py             # GET /macro, /macro/{series}
│       ├── liquidity.py         # GET /liquidity
│       ├── news.py              # GET /news
│       ├── sentiment.py         # GET /sentiment
│       ├── disasters.py         # GET /disasters
│       ├── geopolitical.py      # GET /geopolitical
│       ├── calendar.py          # GET /calendar
│       └── admin.py             # POST /admin/fetch, /compute, /classify, /refresh/*
│
├── frontend/                    # Dash web application
│   ├── app.py                   # App entry point + sidebar layout
│   ├── api_client.py            # HTTP helpers for calling FastAPI
│   ├── config.py                # Dash/API host & port from .env
│   ├── assets/
│   │   └── styles.css           # Dark financial dashboard theme
│   └── pages/
│       ├── dashboard.py         # Intelligence Hub page
│       ├── screener.py          # Stock Screener page
│       ├── screener_rok.py      # Stock Screener ROK (Korea) page
│       ├── etf.py               # ETF Screener page
│       ├── zombies.py           # Zombie Kill List page
│       ├── compare.py           # Batch Compare page
│       ├── technical.py         # Technical Analysis page
│       ├── retirement.py        # Retirement Planner page
│       ├── metals.py            # Metals Intel page
│       ├── macro.py             # Macro Monitor page
│       ├── liquidity.py         # Fed Liquidity page
│       ├── sentiment.py         # News & Sentiment Hub page
│       └── calendar.py          # Economic Calendar page
│
├── scripts/                     # CLI entry points
│   ├── fetch_data.py            # Fetch statements + compute + classify
│   ├── compute_metrics.py       # Recompute metrics + classify
│   └── run_server.py            # Launch FastAPI + Dash together
│
├── lib/                         # External code / vendored libraries
├── data/                        # SQLite database + ETF ticker lists (auto-created)
├── tests/
│   └── test_metrics.py          # Unit tests for metric formulas + zombie classifier
├── .env_template.example        # Environment variable template
└── requirements.txt
```

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env_template.example .env
```

Edit `.env` and set your API keys:

```env
# Required for Macro Monitor & Fed Liquidity pages
FRED_API_KEY=your_fred_api_key_here

# Optional — enables market news feed on News & Sentiment page
NEWSAPI_KEY=your_newsapi_key_here

# Optional — reserved for future use
FINNHUB_API_KEY=
ALPHAVANTAGE_API_KEY=
```

### 3. Fetch data for a starter set of tickers

```bash
python scripts/fetch_data.py AAPL MSFT GOOGL AMZN META NVDA TSLA JPM
```

This will:
1. Download financial statements from yfinance
2. Compute all derived metrics (gross margin, ROIC, FCF margin, interest coverage, P/E, P/B, Graham number, quality score, etc.)
3. Run zombie classification

### 4. Start both servers

```bash
python scripts/run_server.py
```

- **FastAPI** → `http://127.0.0.1:8000` (API docs at `/docs`)
- **Dash UI** → `http://127.0.0.1:8050`

---

## Detailed Usage

### Fetch data

```bash
# Single tickers
python scripts/fetch_data.py AAPL MSFT

# From a file (one ticker per line)
python scripts/fetch_data.py --file my_watchlist.txt

# All S&P 500 (~500 requests, takes several minutes)
python scripts/fetch_data.py --sp500

# Quarterly statements
python scripts/fetch_data.py AAPL --period quarterly
```

### Recompute metrics only (no re-fetching)

```bash
python scripts/compute_metrics.py
python scripts/compute_metrics.py --ticker AAPL MSFT
```

### Run servers independently

```bash
# API only (with hot-reload for development)
python scripts/run_server.py --api-only --reload

# Frontend only
python scripts/run_server.py --frontend-only
```

---

## Metrics Reference

| Metric | Formula | Notes |
|--------|---------|-------|
| Gross Margin % | `(Gross Profit / Revenue) × 100` | Profitability after direct costs |
| ROIC | `NOPAT / Invested Capital` | NOPAT = EBIT × (1 − effective tax rate) |
| FCF Margin % | `(Operating CF − CapEx) / Revenue × 100` | Cash generation efficiency |
| Interest Coverage | `EBIT / Interest Expense` | `null` when no debt |
| P/E Ratio | `Price / Diluted EPS` | `null` when EPS ≤ 0 |
| P/B Ratio | `Price / Book Value per Share` | Price-to-book |
| P/E × P/B | `P/E × P/B` | Combined valuation metric |
| Current Ratio | `Current Assets / Current Liabilities` | Short-term liquidity |
| ROE | `Net Income / Shareholders' Equity` | Return on equity |
| Graham Number | `√(22.5 × EPS × BVPS)` | Benjamin Graham's intrinsic value |
| NCAV per Share | `(Current Assets − Total Liabilities) / Shares` | Net current asset value |
| Owner Earnings/Share | `(Net Income + D&A − CapEx) / Shares` | Buffett's owner earnings |
| Quality Score | Composite of margin, ROIC, FCF, coverage | 0–100 quality ranking |

## Zombie Criteria (configurable)

A company is flagged as **zombie** when it meets **≥ 2** of:

1. Interest coverage ratio ≤ 1.0×
2. Negative FCF margin
3. Gross margin in a declining trend over the last 3 years

---

## Feature Flags

Toggle optional features in `.env`:

| Flag | Default | Controls |
|------|---------|----------|
| `ENABLE_NEWS_FEED` | `true` | News article fetching on sentiment page |
| `ENABLE_GDELT` | `false` | GDELT geopolitical event ingestion |
| `ENABLE_SENTIMENT` | `true` | VIX/Fear & Greed sentiment computation |
| `ENABLE_EARTHQUAKE` | `true` | USGS earthquake data fetching |

---

## Running Tests

```bash
pytest tests/ -v
```

---

## Scheduler

The FastAPI server runs APScheduler background jobs that refresh data
automatically:

- **Equity data** — daily at 06:30 UTC
- **Macro/metals** — daily at 06:45 UTC

Adjust the times via `SCHEDULER_HOUR` and `SCHEDULER_MINUTE` in `.env`.

---

## Adding New Tickers via the UI

On the **Stock Screener** page, type tickers into the "Add & Fetch Tickers"
box (comma-separated) and click the button. Metrics and zombie flags are
computed automatically. You can also trigger refresh for all tickers from the
**Admin** endpoints at `/docs`.
