# Plan: Stock Screener - ROK (Republic of Korea)

## Overview

Add a new Dash page **"Stock Screener - ROK"** that displays Korean-listed stocks (KOSPI `.KS` / KOSDAQ `.KQ`).

Layout is **identical** to the existing US screener (`frontend/pages/screener.py`) with the following differences:
- Page title: **"Stock Screener - ROK"**
- Admin panel label: **"Stock Screener - ROK"**
- Ticker input auto-appends `.KS` or `.KQ` suffix (user selects exchange)
- Screener table only shows tickers whose symbol ends in `.KS` or `.KQ`
- Currency label shows **KRW** (no FX conversion; display as-is from yfinance)

All existing ingestion, metrics, and database logic is **reused** — Korean stocks use the same schema and yfinance fetch path, since yfinance supports `.KS`/`.KQ` suffixes natively.

---

## Architecture Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Filter Korean stocks | Ticker suffix (`.KS` / `.KQ`) | Most reliable; yfinance uses this convention |
| Backend endpoint | Extend `GET /screener` with `?region=rok` param | Avoids duplicating router logic |
| New Dash page | `frontend/pages/screener_rok.py` | Isolated page, identical layout |
| Ticker input UX | Suffix dropdown (`.KS` / `.KQ`) next to input | Prevents manual suffix mistakes |
| Currency display | Show KRW as-is | No FX conversion in MVP |

---

## TDD Implementation Plan

Each step = write ONE failing test → implement minimum code → run all tests → refactor if needed.

---

### Step 1 — Backend: `region` filter in screener query
**File**: `tests/test_screener_rok.py`

```
[x] Test: get_screener_rows with region="rok" returns only .KS and .KQ tickers
```

- Add `region: str | None = None` parameter to `get_screener_rows()` in `src/metrics.py`
- When `region="rok"`, add SQL `WHERE ticker LIKE '%.KS' OR ticker LIKE '%.KQ'`
- All other behaviour unchanged when `region=None`

---

### Step 2 — Backend: `region` query param on `/screener` endpoint
**File**: `tests/test_screener_rok.py`

```
[x] Test: GET /screener?region=rok returns only ROK tickers via API
```

- Add `region: str | None = None` query param to `GET /screener` in `src/api/routers/screener.py`
- Pass through to `get_screener_rows()`

---

### Step 3 — Backend: `GET /screener/export` respects `region` param
**File**: `tests/test_screener_rok.py`

```
[x] Test: GET /screener/export?region=rok returns CSV with only ROK tickers
```

- Add `region` param to export endpoint as well
- Same filter applied before streaming CSV

---

### Step 4 — Frontend: ROK screener Dash page exists and renders
**File**: `tests/test_screener_rok_frontend.py` (or manual smoke test)

```
[x] Test: importing frontend/pages/screener_rok.py succeeds with no errors
[x] Test: layout object is a Dash component (not None)
```

- Create `frontend/pages/screener_rok.py`
- Copy layout from `screener.py`; change title to "Stock Screener - ROK"
- All API calls pass `region="rok"` query parameter
- Register page: `dash.register_page(__name__, path="/screener-rok", name="Screener ROK")`

---

### Step 5 — Frontend: Ticker input has exchange selector (.KS / .KQ)
**File**: `tests/test_screener_rok_frontend.py`

```
[x] Test: layout contains a Dropdown with options [".KS", ".KQ"]
```

- Add a `dcc.Dropdown` with id `rok-exchange-suffix` beside the ticker input
- Options: `[{"label": "KOSPI (.KS)", "value": ".KS"}, {"label": "KOSDAQ (.KQ)", "value": ".KQ"}]`
- Default value: `.KS`

---

### Step 6 — Frontend: Add ticker callback appends suffix automatically
**File**: `tests/test_screener_rok_frontend.py`

```2
[x] Test: add_ticker callback concatenates ticker + selected suffix before POSTing
```

- In the "Add ticker" callback, read `rok-exchange-suffix` value
- Concatenate: `ticker_input.strip().upper() + suffix` before calling `add_ticker()` API
- Strip any existing `.KS`/`.KQ` suffix user may have typed to avoid duplication

---

### Step 7 — Frontend: ROK page linked in navbar
**File**: `frontend/app.py` (or layout component)

```
[x] Test: sidebar/navbar contains a link to "/screener-rok"
```

- Add nav link "Screener ROK" pointing to `/screener-rok`
- Place it adjacent to the existing "Screener" link

---

### Step 8 — Integration: fetch + compute + screen a KRX ticker end-to-end
**File**: `tests/test_screener_rok.py`

```
[x] Test: adding "005930.KS" fetches data, computes metrics, appears in region=rok screener results
```

- Uses real yfinance call (mark as slow/integration test, skip in CI if needed)
- Validates the full pipeline works for a real KOSPI ticker (Samsung Electronics)

---

## File Changes Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `src/metrics.py` | Behavioral | Add `region` param to `get_screener_rows()` |
| `src/api/routers/screener.py` | Behavioral | Add `region` query param to GET endpoints |
| `frontend/pages/screener_rok.py` | Behavioral | New page — ROK screener (clone + modify) |
| `frontend/app.py` | Behavioral | Add nav link for ROK screener page |
| `tests/test_screener_rok.py` | Behavioral | New test file for backend ROK filtering |

---

## Out of Scope (MVP)

- FX conversion (KRW → USD)
- Separate ROK zombie detector page
- KRX-specific data sources (DART, KIS API)
- Real-time KRX price feed
- Korean company name display (한글)
