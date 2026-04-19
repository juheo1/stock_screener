# Known Gaps and Uncertainties

**Purpose**: Flag what could not be inferred confidently, ambiguous ownership zones,
suspected legacy code, technical debt, and recommended next doc improvements.

---

## Confidence Labels Used in This Docs Set

| Label | Meaning |
|-------|---------|
| Confirmed | Verified by reading actual source files |
| Strong inference | Consistent with README + ARCHITECTURE.md + code structure |
| Weak inference | Based on naming convention or partial evidence only |
| Unknown | Docs are silent; inspect source before acting |

---

## Architectural Uncertainties

### 1. `ARCHITECTURE.md` is Partially Stale
**Status**: Weak inference
The root `ARCHITECTURE.md` was written earlier and lists some file paths that differ from
the current directory listing (e.g., it references `src/fetcher.py`, `src/screener.py`,
`src/zombies.py`, `src/db.py` — but the actual files are named `src/ingestion/equity.py`,
`src/zombie.py`, `src/database.py`). **Do not trust ARCHITECTURE.md file paths without verification.**
The `docs/` hierarchy supersedes it for navigation purposes.

### 2. Screener Router's On-the-Fly Metrics
**Status**: Strong inference (from README, not verified in router source)
`src/api/routers/screener.py` reportedly computes `pe_x_pb`, `net_net_flag`, `ltd_lte_nca`,
`roe_leveraged` on-the-fly rather than reading from stored columns. If changing screener
output, verify whether these are computed in the router or in metrics.py.

### 3. Technical Page's Dependency on Strategy Engine
**Status**: Confirmed (engine.py read)
`frontend/pages/technical.py` injects its own private functions (`_get_source`, `_compute_ma`,
`_compute_indicator`) into `StrategyContext` at call time. If these private functions are
renamed or moved, all built-in strategy tests will break. The injection pattern is correct
but the coupling is tight.

### 4. Strategy UI Integration in `technical.py`
**Status**: Strong inference (plan doc + engine.py read; `technical.py` itself not fully read)
The strategy panel UI (dropdowns, run button, parameter inputs, performance table) is
implemented in `frontend/pages/technical.py` but only described in `plan/strategy_system_plan.md`.
The page has uncommitted changes on the current branch. Actual callback IDs, store names,
and layout details must be verified by reading `technical.py` before editing the strategy UI.

### 5. `screener_rok.py` Korean Screener
**Status**: Weak inference
The Korean screener (`frontend/pages/screener_rok.py`) has both a backend test
(`test_screener_rok.py`) and a frontend test (`test_screener_rok_frontend.py`), suggesting
it has its own logic path. Whether it shares the same `src/api/routers/screener.py` router
or has a separate one is unknown without reading the file.

---

## Test Coverage Gaps

| Module | Gap | Risk |
|--------|-----|------|
| `src/retirement.py` | No unit tests | Medium — Monte Carlo math could drift silently |
| `src/api/routers/` (most) | No integration tests | Medium — endpoint contracts not validated |
| `frontend/pages/*.py` (most) | No Dash callback tests | Low — visual verification required |
| `frontend/strategy/builtins/ma_crossover.py` | No dedicated test | Low |
| `frontend/strategy/builtins/mean_reversion.py` | No dedicated test | Low |
| `src/ingestion/equity.py` | No unit tests | Medium — yfinance format changes could break silently |
| `src/ingestion/macro.py` | No unit tests | Low — FRED API is stable |

---

## Suspected Legacy / Dead Code Areas

### `ARCHITECTURE.md` (root)
Contains stale file paths (see §1 above). Not dead code, but misleading documentation.
Recommend updating or clearly marking as "superseded by docs/".

### `script/` directory (vs `scripts/`)
There is a `script/` directory (singular) alongside `scripts/` (plural). The README and
docs reference only `scripts/`. Contents of `script/` are unknown — may be legacy.
**Status**: Unknown — inspect before deleting.

### `lib/` directory
Described as "External code / vendored libraries" in README. Contents not inspected.
May contain vendored packages or be empty.
**Status**: Unknown — inspect before assuming safe to ignore.

### `notebook/` directory
Not referenced in README or primary docs. Likely Jupyter notebooks used for exploration.
**Status**: Weak inference — probably safe to ignore for application code changes.

### Auth packages in `requirements.txt`
`python-jose` and `passlib` are listed as dependencies but no auth middleware or
protected endpoints were observed in the architecture. These may be reserved for
future auth work or be leftover from an earlier design.
**Status**: Weak inference.

---

## Technical Debt Relevant to AI Agents

| Debt Item | Location | Impact |
|-----------|----------|--------|
| `technical.py` is ~2 100 lines | `frontend/pages/technical.py` | Hard to navigate; high collision risk when multiple features edit the same file |
| No Alembic / formal migrations | `src/database.py` | `_migrate_columns()` is hand-rolled; adding columns to existing tables is fine, but renames/drops are not handled |
| Dynamic `importlib` strategy loading | `frontend/strategy/engine.py` | User strategy files execute arbitrary Python in the Dash process — intentional for extensibility but a security consideration in multi-user deployments |
| Frontend calls yfinance directly | `frontend/pages/technical.py` | yfinance API changes must be patched in two places: `src/ingestion/equity.py` AND `technical.py` |
| Hardcoded economic calendar | `src/ingestion/calendar_events.py` | FOMC/CPI/NFP dates are hardcoded through 2026; needs manual update each year |
| Missing lint / type-check config | root | No `pyproject.toml`, `.flake8`, or `mypy.ini` found — type safety not enforced |

---

## Recommended Next Documentation Improvements

Priority order for a future agent:

1. **Read and verify `frontend/pages/technical.py`** — this is the largest file and the
   most active area. Document the callback IDs, store names, and strategy UI panel
   structure in a dedicated `docs/05_technical_chart/` note.

2. **Verify `src/api/routers/screener.py`** — confirm which metrics are computed on-the-fly
   vs. read from DB. Update `module-responsibility-map.md` and `api-contracts-and-extension-points.md`.

3. **Inspect `script/` (singular)** — determine if it contains anything or can be deleted.

4. **Inspect `lib/`** — catalog vendored libraries.

5. **Add retirement planner tests** — highest-value gap given the math complexity.
