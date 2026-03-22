# Stock Intelligence Suite — Architecture Reference

Quick reference for navigating the codebase without re-reading every file.

---

## High-Level Layout

```
stock_screener/
├── src/                        Backend (FastAPI)
│   ├── api/
│   │   ├── main.py             App factory, router registration
│   │   ├── schemas.py          Pydantic request/response models (all endpoints)
│   │   └── routers/
│   │       ├── retirement.py   POST /retirement
│   │       ├── screener.py     GET  /screener, /presets
│   │       ├── etf.py          GET  /etf, /etf/groups, POST /etf/refresh
│   │       ├── zombies.py      GET  /zombies
│   │       ├── compare.py      POST /compare
│   │       ├── metals.py       GET  /metals, /metals/{id}/history, stack CRUD
│   │       ├── macro.py        GET  /macro, /macro/{series_id}
│   │       └── admin.py        POST /admin/fetch|compute|classify|refresh/*
│   ├── retirement.py           Retirement planning engine (planning + Monte Carlo)
│   ├── screener.py             Screening/filtering logic
│   ├── zombies.py              Zombie classification logic
│   ├── metrics.py              Financial metric computation
│   ├── fetcher.py              yfinance data ingestion
│   └── db.py                   SQLite database layer
├── frontend/
│   ├── app.py                  Dash app init, sidebar, root layout, nav callback
│   ├── config.py               API_BASE_URL, DASH_HOST/PORT/DEBUG
│   ├── api_client.py           HTTP wrapper functions (one per endpoint)
│   ├── assets/
│   │   ├── style.css           Global dark-theme CSS
│   │   └── prevent_wheel.js    Prevents scroll-wheel on number inputs
│   └── pages/                  One file per Dash page (use_pages=True)
│       ├── home.py             / — Intelligence Hub dashboard
│       ├── screener.py         /screener
│       ├── etf.py              /etf
│       ├── technical.py        /technical
│       ├── zombies.py          /zombies
│       ├── compare.py          /compare
│       ├── retirement.py       /retirement — Retirement Planner
│       ├── metals.py           /metals
│       └── macro.py            /macro
├── scripts/
│   └── run_server.py           Starts FastAPI (:8000) + Dash (:8050) together
└── ARCHITECTURE.md             This file
```

---

## Key Files by Concern

### Retirement Planner (most complex feature)

| File | What it does |
|------|-------------|
| `src/retirement.py` | Core engine. `calculate_retirement_planning()` → deterministic nest-egg + required-return-rate. `run_retirement_projection()` → Monte Carlo fan chart. Data classes: `RetirementParams`, `PlanningResult`, `ScenarioResult`. |
| `src/api/schemas.py` | `RetirementRequest` (all input fields), `RetirementResponse`, `PlanningResultSchema`, `ScenarioResultSchema`. |
| `src/api/routers/retirement.py` | `POST /retirement` handler. Calls planning engine, optionally runs MC (`run_mc=False` skips MC for speed). |
| `frontend/api_client.py` | `run_retirement(...)` function — thin HTTP POST wrapper. |
| `frontend/pages/retirement.py` | Dash UI. Two buttons: "Generate Planning Summary" (`ret-plan-btn`) and "Run Monte Carlo" (`ret-mc-btn`). Single combined callback `run_analysis` uses `ctx.triggered_id`. Results in `ret-planning-results` and `ret-mc-results` divs. Form persistence via `dcc.Store(id="ret-form-store", storage_type="local")` defined in `frontend/app.py`. |

### Account types tracked by the retirement engine

| Account | Tax treatment | IRS limit |
|---------|--------------|-----------|
| Taxable | Capital gains on growth above cost basis | None |
| Traditional 401k | Ordinary income tax on withdrawal | $23,500/yr employee |
| Roth 401k | Tax-free | Shared with Trad 401k ($23,500 combined) |
| Roth IRA | Tax-free | $7,000/yr (separate from 401k) |

### Form Persistence Pattern (Dash Pages)

Problem: Dash `use_pages=True` unmounts/remounts page components on navigation, resetting all input values to their `value=` props.

Solution:
- `dcc.Store(id="ret-form-store", storage_type="local")` lives in **`app.py`** root layout (not the page), so it survives navigation.
- **Saving**: `run_analysis` callback (button click) writes a snapshot to the store. Never saved on component mount to avoid race conditions.
- **Restoring**: `restore_form` callback fires on `url.pathname` change → `/retirement`, reads store, outputs to all input components.

### Input Type Decisions

- Dollar-amount inputs use `type="text"` + `inputMode="numeric"` (not `type="number"`) to avoid:
  - Browser scroll-wheel incrementing the value
  - React controlled-input state mismatches that caused `State` to read stale values
- Age / percentage inputs use `type="number"` (small integers, scroll-wheel increment is acceptable)

---

## Data Flow

```
User (browser)
    │  HTTP
    ▼
Dash frontend (:8050)
    │  requests.post/get  (frontend/api_client.py)
    ▼
FastAPI backend (:8000)
    │  calls
    ▼
Business logic (src/*.py)
    │  reads/writes
    ▼
SQLite DB (data/*.db)
```

---

## Adding a New Feature — Checklist

1. **Schema**: add fields to `src/api/schemas.py` (request + response models)
2. **Engine**: update `src/<module>.py` business logic
3. **Router**: update `src/api/routers/<router>.py` to pass new fields
4. **API client**: update `frontend/api_client.py` function signature + body dict
5. **UI**: update `frontend/pages/<page>.py` layout + callbacks
6. **Store**: if new inputs need persistence, add to snapshot dict + restore_form outputs
