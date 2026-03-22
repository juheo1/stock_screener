# Back End Plan

## 1. Data ingestion layer

### Financial statement data (equities)
Goal: collect the inputs needed to compute the screener metrics and derived scores.

Typical required fields:
- Income statement: revenue, COGS, gross profit, EBIT/operating income, interest expense, net income, diluted shares
- Balance sheet: total assets, current liabilities, cash, total debt, equity, working capital items
- Cash flow statement: operating cash flow, capex, free cash flow inputs

Possible free sources:
- Public market data providers that offer free tiers (rate-limited).
- Company filings (SEC EDGAR) for US issuers if you want first-party data.
- For a PC-local tool, start with a single provider and keep source adapters modular so you can swap later.

### Macro data
For the macro monitor:
- FRED series (M2, reverse repo, rates, etc.)
Store daily time series for charts.

### Metals data
For metals intel:
- Spot prices (gold, silver, platinum, palladium, copper).
- Inventory series (COMEX warehouses), if you can access a stable free source.

### Storage
Start local, then scale:
- SQLite for local-first development
- PostgreSQL if you want multi-user and concurrency

Tables (minimum):
- equities (ticker, name, exchange, sector, industry, currency)
- statements_income (ticker, period_end, values...)
- statements_balance (ticker, period_end, values...)
- statements_cashflow (ticker, period_end, values...)
- metrics_quarterly (ticker, period_end, gross_margin, roic, fcf_margin, interest_cov, pe, etc.)
- flags (ticker, asof_date, is_zombie, reasons_json)
- macro_series (series_id, date, value)
- metals_series (metal_id, date, spot_price, inventory_optional)
- user_portfolios (user_id, portfolio_json, settings_json)
- user_metal_stack (user_id, transactions_json)

## 2. Metric computation service
Compute and store derived metrics on schedule.

Core formulas:
- Gross margin % = (revenue - COGS) / revenue * 100 [S1]
- ROIC = NOPAT / invested_capital, with NOPAT often approximated as EBIT * (1 - tax_rate) [S2]
- FCF margin % = free_cash_flow / revenue * 100, with FCF = operating_cash_flow - capex [S3]
- Interest coverage = EBIT / interest_expense [S4]
- P/E ratio = price / EPS [S5]

Notes for implementation:
- Keep units explicit (percent vs ratio).
- Track as-of date and statement period end.
- Define NA behavior (for example, interest expense = 0 -> coverage = +inf, but store a flag).

## 3. Zombie classifier
Rule-based (v1), later upgradeable to a scoring model.

Example definition (configurable thresholds):
- FCF < 0
- Interest coverage < 1.0
- Gross margin trend negative over last N years

Outputs:
- is_zombie boolean
- reasons (list)
- severity score (0-100), optional

## 4. Retirement modeling engine
Inputs:
- holdings (ticker, weight or shares)
- contributions schedule
- retirement age, target horizon
- assumptions: expected return, volatility, inflation

Outputs:
- three scenarios: conservative, expected, optimistic
- year-by-year projection arrays
- probability of meeting target (readiness score)

Start simple:
- lognormal returns with correlation assumptions
- later: historical bootstrapping per asset class

## 5. Job orchestration
Local-first options:
- cron + python scripts
- APScheduler inside the FastAPI app (simple)

If you later want reliability:
- Celery + Redis (or RQ)
