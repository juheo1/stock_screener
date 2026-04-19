# Test and Validation Guide

**Purpose**: Where tests live, how they are organized, what to run for common edit types,
and how to do fast vs. deep verification.

---

## Test Layout

All tests live in `tests/`. Flat structure — no subdirectories.

```
tests/
  __init__.py
  test_metrics.py              ← financial metrics + zombie classifier
  test_bb_strategy.py          ← BB Trend-Filtered Pullback strategy
  test_candles.py              ← candle-shape helpers (candles.py)
  test_indicators.py           ← indicator helpers (indicators.py)
  test_risk.py                 ← trade management (risk.py)
  test_screener_rok.py         ← Korean screener backend
  test_screener_rok_frontend.py ← Korean screener UI
  test_liquidity.py            ← fed liquidity computation
  test_macro_regime_presets.py ← macro regime preset logic
  test_sentiment_news.py       ← news fetch + VADER sentiment
  test_geopolitical.py         ← GDELT geopolitical data
```

---

## Running Tests

### Run all tests
```bash
pytest tests/ -v
```

### Run a specific test file
```bash
pytest tests/test_metrics.py -v
pytest tests/test_bb_strategy.py -v
```

### Run by keyword
```bash
pytest tests/ -v -k "zombie"
pytest tests/ -v -k "strategy"
pytest tests/ -v -k "candle or indicator or risk"
```

### Run with coverage report
```bash
pytest tests/ --cov=src --cov=frontend/strategy --cov-report=term-missing
```

---

## What to Run for Common Edit Types

| What you changed | Tests to run |
|-----------------|-------------|
| `src/metrics.py` | `pytest tests/test_metrics.py -v` |
| `src/zombie.py` | `pytest tests/test_metrics.py -v` (zombie tests are included there) |
| `src/ingestion/liquidity.py` | `pytest tests/test_liquidity.py -v` |
| `src/ingestion/news.py`, `sentiment.py` | `pytest tests/test_sentiment_news.py -v` |
| `src/ingestion/geopolitical.py` | `pytest tests/test_geopolitical.py -v` |
| `frontend/strategy/candles.py` | `pytest tests/test_candles.py -v` |
| `frontend/strategy/indicators.py` | `pytest tests/test_indicators.py -v` |
| `frontend/strategy/risk.py` | `pytest tests/test_risk.py -v` |
| `frontend/strategy/builtins/bb_trend_pullback.py` | `pytest tests/test_bb_strategy.py -v` |
| New built-in strategy | Create `tests/test_<name>_strategy.py` |
| `frontend/pages/screener_rok.py` | `pytest tests/test_screener_rok_frontend.py -v` |
| Any macro / regime logic | `pytest tests/test_macro_regime_presets.py -v` |
| After any change | `pytest tests/ -v` (full suite) |

---

## Fast Verification vs. Deep Validation

### Fast (< 30 seconds)
- Run the single relevant test file.
- For strategy changes: `pytest tests/test_<name>_strategy.py -v`
- For metric changes: `pytest tests/test_metrics.py -v`

### Deep Validation
- Run the full suite: `pytest tests/ -v`
- Start servers and manually verify the affected page in the browser.
- For data changes: run `python scripts/fetch_data.py AAPL --period annual` and inspect DB.

---

## Test Coverage Gaps (Confirmed)

The following areas have **no test files** as of the current codebase scan:

| Area | Gap |
|------|-----|
| `src/retirement.py` | No dedicated unit tests for Monte Carlo or planning engine |
| `frontend/pages/*.py` (most pages) | Dash callback testing not present |
| `src/api/routers/` (most routers) | Integration tests via httpx are minimal |
| `frontend/strategy/builtins/ma_crossover.py` | No dedicated test file found |
| `frontend/strategy/builtins/mean_reversion.py` | No dedicated test file found |

See `docs/04_maintenance/known-gaps-and-uncertainties.md` for full gap list.

---

## Linting and Type Checking

No configured linter or type-checker was found in the repository (no `pyproject.toml`,
`setup.cfg`, or `.flake8` at root level — **weak inference** based on absence of these files).

If adding lint/type checks, suggested commands:
```bash
# Type checking
mypy src/ frontend/ --ignore-missing-imports

# Linting
ruff check src/ frontend/ tests/
```

---

## Test Dependency Notes

- Tests that exercise `src/` modules may require a writable SQLite DB or mocking.
- Tests for `frontend/strategy/` are pure Python (pandas/numpy) — no server required.
- Tests that call external APIs (yfinance, FRED, NewsAPI) should be skipped in CI
  or mocked to avoid flakiness. Check `tests/test_sentiment_news.py` for the
  existing pattern.
