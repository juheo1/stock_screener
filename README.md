# Stock Intelligence & Screener

A local web application for stock intelligence and screening, inspired by
professional financial intelligence suites. Python powers the data pipeline,
metrics engine, and REST API. A Dash web UI provides all the interactive views.

---

## Features

| Module | Description |
|--------|-------------|
| **Intelligence Hub** | Summary KPIs, market index cards, FRED macro values, metals spot prices |
| **Stock Screener** | Threshold-based filtering on 5 core metrics with presets and CSV export |
| **Zombie Kill List** | Rule-based solvency-risk detector (FCF, interest coverage, margin trend) |
| **Batch Compare** | Side-by-side heatmap for up to 50 tickers with Excel export |
| **Retirement Planner** | Monte Carlo projection with 3 scenarios and readiness score |
| **Metals Intel** | Spot prices, price history, gold/silver ratio, personal stack tracker |
| **Macro Monitor** | FRED time-series charts (M2, reverse repo, rates, CPI, yield curve) |

---

## Project Structure

```
stock_screener/
├── src/                     # Backend Python package
│   ├── config.py            # Settings loaded from .env
│   ├── database.py          # SQLAlchemy engine, session, init
│   ├── models.py            # ORM table definitions
│   ├── metrics.py           # Metric computation (gross margin, ROIC, FCF, etc.)
│   ├── zombie.py            # Zombie-company classifier
│   ├── retirement.py        # Monte Carlo retirement engine
│   ├── scheduler.py         # APScheduler daily refresh jobs
│   └── ingestion/
│       ├── equity.py        # yfinance financial-statement fetcher
│       ├── macro.py         # FRED macro series fetcher
│       └── metals.py        # yfinance metals price fetcher
│
├── src/api/                 # FastAPI application
│   ├── main.py              # App factory + CORS + lifecycle
│   ├── deps.py              # Shared dependencies (DB session)
│   ├── schemas.py           # Pydantic request/response models
│   └── routers/
│       ├── dashboard.py     # GET /dashboard
│       ├── screener.py      # GET /screener, /presets, /screener/export
│       ├── zombies.py       # GET /zombies, /zombies/export
│       ├── compare.py       # POST /compare, /compare/export.xlsx
│       ├── retirement.py    # POST /retirement
│       ├── metals.py        # GET /metals, /metals/{id}/history, stack endpoints
│       ├── macro.py         # GET /macro, /macro/{series}
│       └── admin.py         # POST /admin/fetch, /compute, /classify, /refresh/*
│
├── frontend/                # Dash web application
│   ├── app.py               # App entry point + sidebar layout
│   ├── api_client.py        # HTTP helpers for calling FastAPI
│   ├── config.py            # Dash/API host & port from .env
│   ├── assets/
│   │   └── styles.css       # Dark financial dashboard theme
│   └── pages/
│       ├── dashboard.py     # Intelligence Hub page
│       ├── screener.py      # Stock Screener page
│       ├── zombies.py       # Zombie Kill List page
│       ├── compare.py       # Batch Compare page
│       ├── retirement.py    # Retirement Planner page
│       ├── metals.py        # Metals Intel page
│       └── macro.py         # Macro Monitor page
│
├── scripts/                 # CLI entry points
│   ├── fetch_data.py        # Fetch statements + compute + classify
│   ├── compute_metrics.py   # Recompute metrics + classify
│   └── run_server.py        # Launch FastAPI + Dash together
│
├── lib/                     # External code / vendored libraries
├── data/                    # SQLite database (auto-created)
├── tests/
│   └── test_metrics.py      # Unit tests for metric formulas + zombie classifier
├── .env.example             # Environment variable template
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
cp .env.example .env
```

Edit `.env` and set at minimum:
- `FRED_API_KEY` — free key from https://fred.stlouisfed.org/docs/api/api_key.html
  (required for macro data; other features work without it)

### 3. Fetch data for a starter set of tickers

```bash
python scripts/fetch_data.py AAPL MSFT GOOGL AMZN META NVDA TSLA JPM
```

This will:
1. Download financial statements from yfinance
2. Compute all derived metrics (gross margin, ROIC, FCF margin, interest coverage, P/E)
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

## Zombie Criteria (configurable)

A company is flagged as **zombie** when it meets **≥ 2** of:

1. Interest coverage ratio ≤ 1.0×
2. Negative FCF margin
3. Gross margin in a declining trend over the last 3 years

---

## Data Sources

| Data | Source | Key |
|------|--------|-----|
| Equity statements & prices | [yfinance](https://github.com/ranaroussi/yfinance) | None (free) |
| Metals spot prices | yfinance futures (GC=F, SI=F…) | None (free) |
| FRED macro series | [fredapi](https://github.com/mortada/fredapi) | Free at fred.stlouisfed.org |

---

## Running Tests

```bash
pytest tests/ -v
```

---

## Scheduler

The FastAPI server runs an APScheduler background job that refreshes equity
data daily at 06:30 UTC and macro/metals at 06:45 UTC.  Adjust the times via
`SCHEDULER_HOUR` and `SCHEDULER_MINUTE` in `.env`.

---

## Adding New Tickers via the UI

On the **Stock Screener** page, type tickers into the "Add & Fetch Tickers"
box (comma-separated) and click the button.  Metrics and zombie flags are
computed automatically.  You can also trigger refresh for all tickers from the
**Admin** endpoints at `/docs`.
