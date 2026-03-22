# API Plan (FastAPI recommended)

## Core principles
- All reads should be paginated.
- All endpoints should support an "as_of" date (latest by default).
- Provide CSV export endpoints that reuse the same query layer as JSON endpoints.

## Endpoints

### Dashboard
GET /dashboard
Returns:
- summary counts (screened, zombies, quality)
- key market cards (S&P 500 proxy, VIX proxy, etc.)
- latest macro series values
- latest metals spot prices

### Screener
GET /screener
Query params (examples):
- min_gross_margin
- min_roic
- min_fcf_margin
- min_interest_coverage
- max_pe
- hide_na (bool)
- sort_by, sort_dir
- page, page_size

Returns:
- rows with ticker, company, and selected metrics
- computed pass/fail flags per metric (for coloring)

### Presets
GET /presets
Returns saved presets:
- high_quality
- value
- growth
- zombie
Each preset includes default thresholds and scoring weights.

### Zombies
GET /zombies
Query params:
- search (ticker/name)
- sector
- page, page_size

Returns:
- ticker, company
- zombie reasons
- metrics snapshot

GET /zombies/export.csv
Same query params, returns CSV.

### Compare
POST /compare
Body:
- tickers: list[str] (max 50)
- optional thresholds (to show pass/fail)

Returns:
- per-ticker metrics
- overall score
- heatmap metadata (per-cell color band)

Export:
- POST /compare/export.xlsx
- POST /compare/export.pdf

### Retirement
POST /retirement
Body:
- portfolio (holdings)
- ages, contributions
- scenario assumptions

Returns:
- scenario projections
- readiness score

### Metals
GET /metals
Returns:
- spot prices for gold, silver, platinum, palladium, copper
- gold/silver ratio
- inventory series summary if available

Authenticated user endpoints:
- POST /metals/stack/transaction
- GET /metals/stack/summary

## Auth
- JWT access tokens (local app can still use auth to separate profiles)
- Store only necessary user data (portfolios, saved screens, metal stack)
