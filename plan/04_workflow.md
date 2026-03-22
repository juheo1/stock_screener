# Build Workflow

## Phase 0 - Repo skeleton
- Set up folders (backend, frontend, docs, scripts).
- Add a minimal environment file and a local run script.

## Phase 1 - UI prototype with mock data
- Implement dashboard layout, screener layout, compare layout.
- Confirm interaction model (sliders, table sorting, exports).

## Phase 2 - Data layer and metrics
- Implement ingestion for a small ticker set.
- Compute gross margin, ROIC, FCF margin, interest coverage, P/E.
- Write unit tests for each metric computation.

## Phase 3 - API + UI integration
- Implement /screener, /zombies, /compare endpoints.
- Hook the UI to live endpoints.
- Add CSV export.

## Phase 4 - Retirement + metals + macro
- Add /retirement endpoint and UI.
- Add /metals endpoint and UI.
- Add macro charts from FRED.

## Phase 5 - Hardening
- caching (avoid recompute on each query)
- data freshness indicators
- logging and error handling
- packaged local deployment (Docker optional)

## Definition of done (v1)
- Screener works with thresholds and exports.
- Zombie list works with explanations and exports.
- Compare tool works for up to 50 tickers.
- Data updates on demand (manual button) or daily schedule.
