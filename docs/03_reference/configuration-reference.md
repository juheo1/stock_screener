# Configuration Reference

**Purpose**: All configuration files, environment variables, defaults, and where
configuration enters the system.

---

## Environment Variables

Defined in `.env` (copy from `.env_template.example`). Loaded by `src/config.py`
via Pydantic Settings.

### API Keys

| Variable | Required | Used By | Default |
|----------|----------|---------|---------|
| `FRED_API_KEY` | Recommended | `src/ingestion/macro.py`, `src/ingestion/liquidity.py` | `""` (feature silently skipped) |
| `NEWSAPI_KEY` | Optional | `src/ingestion/news.py` | `""` |
| `FINNHUB_API_KEY` | Optional | Reserved, not currently active | `""` |
| `ALPHAVANTAGE_API_KEY` | Optional | Reserved, not currently active | `""` |

### Server Config

| Variable | Default | Purpose |
|----------|---------|---------|
| `API_HOST` | `127.0.0.1` | FastAPI bind address |
| `API_PORT` | `8000` | FastAPI port |
| `DASH_HOST` | `127.0.0.1` | Dash bind address |
| `DASH_PORT` | `8050` | Dash port |
| `DASH_DEBUG` | `false` | Dash debug/hot-reload mode |

### Database

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | `sqlite:///./data/stock_screener.db` | SQLAlchemy connection string |

### Scheduler

| Variable | Default | Purpose |
|----------|---------|---------|
| `SCHEDULER_HOUR` | `6` | Hour (UTC) for daily data refresh |
| `SCHEDULER_MINUTE` | `30` | Minute for daily data refresh |

### Feature Flags

| Variable | Default | Controls |
|----------|---------|---------|
| `ENABLE_NEWS_FEED` | `true` | News article fetching on Sentiment page |
| `ENABLE_GDELT` | `false` | GDELT geopolitical event ingestion |
| `ENABLE_SENTIMENT` | `true` | VIX / Fear & Greed sentiment computation |
| `ENABLE_EARTHQUAKE` | `true` | USGS earthquake data fetching |

---

## Configuration Files

### `src/config.py`

**Confirmed** entry point for all backend configuration. Implements a Pydantic
`BaseSettings` class (likely named `Settings`). Exposes a module-level `settings`
singleton. All `src/` modules import `settings` from here.

### `frontend/config.py`

Frontend-side configuration. Provides:
- `API_BASE_URL` — URL of the FastAPI server (e.g. `http://127.0.0.1:8000`)
- `DASH_HOST`, `DASH_PORT`, `DASH_DEBUG`

These are consumed by `frontend/api_client.py` and `frontend/app.py`.

### `requirements.txt`

Python package versions. Pinned with `>=` lower bounds. Used by `pip install -r requirements.txt`.

---

## Runtime Data / Preset Configuration

### Chart Presets
- Location: `data/technical_chart/<preset_name>.json`
- Format: Schema version 1 JSON (indicator specs, fill-between config)
- Managed by: `frontend/pages/technical.py` (`_save_preset`, `_load_preset`, `_delete_preset`)

### Strategy Files
- Location: `data/strategies/<slug>.py` + `<slug>.json`
- Format: Python strategy file + JSON metadata sidecar
- Managed by: `frontend/strategy/engine.py` (`save_user_strategy`, `delete_user_strategy`)

### Built-in Strategy Metadata
- Location: `frontend/strategy/builtins/<slug>.json`
- Keys: `version`, `name`, `display_name`, `description`, `created`, `modified`, `default_params`

---

## Zombie Thresholds (Database-Stored Config)

Zombie classification thresholds are stored in the SQLite DB in a `ZombieThresholds`
table. This allows runtime configuration without code changes. Defaults:
- Interest coverage threshold: `1.0` (flagged if ≤ this)
- FCF margin: negative (flagged if < 0)
- Gross margin trend: declining over 3 years
- Min criteria met: `2` of 3

---

## Where to Change Defaults

| What to change | Where to change it |
|----------------|--------------------|
| API keys | `.env` |
| Server ports | `.env` |
| Scheduler timing | `.env` (`SCHEDULER_HOUR`, `SCHEDULER_MINUTE`) |
| Feature on/off | `.env` (feature flag vars) |
| Zombie thresholds | DB via admin UI or directly in `ZombieThresholds` table |
| Default metric formula | `src/metrics.py` |
| Default retirement scenarios | `src/retirement.py` |
| Default strategy parameters | `PARAMS` dict in each strategy file |
| Chart preset schema version | `frontend/pages/technical.py` (preset I/O section) |
