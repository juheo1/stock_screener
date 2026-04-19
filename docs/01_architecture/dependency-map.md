# Dependency Map

**Purpose**: Internal module dependencies, external library usage, and coupling risks.

---

## Internal Module Dependencies

### Backend (`src/`)

```
src/api/main.py
  └─ imports: src/api/routers/* (all routers)
              src/scheduler.py (starts on lifespan)

src/api/routers/<router>.py
  └─ imports: src/api/schemas.py
              src/api/deps.py       (DB session)
              src/<business>.py     (metrics, zombie, retirement, etc.)

src/metrics.py
  └─ imports: src/models.py
              src/database.py

src/zombie.py
  └─ imports: src/models.py
              src/database.py

src/retirement.py
  └─ imports: (pure Python / numpy / scipy — no src/* imports)

src/ingestion/*.py
  └─ imports: src/models.py
              src/database.py
              src/config.py

src/scheduler.py
  └─ imports: src/ingestion/*.py
              src/metrics.py
              src/zombie.py

src/database.py
  └─ imports: src/models.py
              src/config.py
```

### Frontend (`frontend/`)

```
frontend/app.py
  └─ imports: frontend/pages/* (auto-registered via use_pages)
              frontend/config.py

frontend/pages/<page>.py
  └─ imports: frontend/api_client.py

frontend/pages/technical.py
  └─ imports: frontend/api_client.py  (for screener ticker list only — weak inference)
              frontend/strategy/engine.py
              yfinance (direct)

frontend/strategy/engine.py
  └─ imports: frontend/strategy/indicators.py (indirectly, via strategy modules)
              frontend/strategy/candles.py
              frontend/strategy/risk.py
              [user strategy modules loaded dynamically via importlib]

frontend/strategy/builtins/<name>.py
  └─ imports: frontend/strategy/engine.py (StrategyContext, StrategyResult)
              frontend/strategy/indicators.py
              frontend/strategy/candles.py
              frontend/strategy/risk.py
```

---

## External Dependencies

| Library | Used By | Why |
|---------|---------|-----|
| `fastapi` | `src/api/` | REST framework |
| `uvicorn` | `scripts/run_server.py` | ASGI server |
| `sqlalchemy` | `src/database.py`, `src/models.py` | ORM + SQLite |
| `pydantic` | `src/api/schemas.py`, `src/config.py` | Data validation, settings |
| `yfinance` | `src/ingestion/equity.py`, `src/ingestion/metals.py`, `src/ingestion/etf.py`, `frontend/pages/technical.py` | Financial data |
| `pandas` | `src/metrics.py`, `src/ingestion/*`, `frontend/strategy/*` | Data processing |
| `numpy` | `src/metrics.py`, `src/retirement.py` | Numeric computation |
| `scipy` | `src/retirement.py` | Monte Carlo / statistical functions |
| `fredapi` | `src/ingestion/macro.py`, `src/ingestion/liquidity.py` | FRED macro data |
| `requests` | `src/ingestion/disasters.py`, `src/ingestion/geopolitical.py`, `src/ingestion/news.py` | External HTTP calls |
| `vaderSentiment` | `src/ingestion/news.py` | NLP sentiment scoring |
| `apscheduler` | `src/scheduler.py` | Background job scheduling |
| `dash` | `frontend/` | Web UI framework |
| `plotly` | `frontend/pages/*` | Charts and figures |
| `dash_ag_grid` | `frontend/pages/screener.py`, `frontend/pages/compare.py` (inferred) | Data grid tables |
| `dash_bootstrap_components` | `frontend/` | Bootstrap layout components |
| `openpyxl` | `src/api/routers/compare.py`, `src/api/routers/screener.py` (inferred) | Excel export |
| `python-jose`, `passlib` | `src/api/` | Auth utilities (reserved, not actively used in UI) |

---

## Risky or Tight Coupling

| Risk | Location | Details |
|------|----------|---------|
| `technical.py` size | `frontend/pages/technical.py` | ~2 100 lines; callbacks, chart builder, and indicator logic all co-located |
| Circular import risk | `frontend/strategy/engine.py` | Injects `_get_source_fn`, `_compute_ma_fn`, `_compute_indicator_fn` from `technical.py` at call time to avoid circular imports — correct pattern but fragile if signatures change |
| `importlib` dynamic loading | `frontend/strategy/engine.py` | User strategy `.py` files execute arbitrary code — intentional for extensibility |
| `_migrate_columns()` implicit contract | `src/database.py` | Adding new columns requires updating both `src/models.py` AND the migration helper |
| yfinance direct in frontend | `frontend/pages/technical.py` | Technical chart bypasses the API layer — any yfinance breaking change must be fixed in both `src/ingestion/equity.py` AND `technical.py` |

---

## Foundational Modules (edit with care)

These modules are imported by many others; changes ripple widely:

| Module | Dependents |
|--------|-----------|
| `src/models.py` | All ingestion modules, metrics, zombie, API routers |
| `src/database.py` | All ingestion modules, metrics, zombie |
| `src/config.py` | Ingestion, database, scheduler |
| `frontend/api_client.py` | All frontend pages |
| `frontend/strategy/engine.py` | All strategy modules + `technical.py` |
