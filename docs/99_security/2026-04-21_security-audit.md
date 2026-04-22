# Security Audit Report

**Date**: 2026-04-21
**Scope**: Full repository — tracked files, git history, all branches
**Branch audited from**: `trade_tracking_feature`
**Branches in repo**: `main`, `strategy_system_plan`, `trade_tracking_feature`
**Tags**: None

---

## A. Verdict

| Question | Answer |
|----------|--------|
| **Public GitHub safe?** | **No** — database file with user data is tracked; hardcoded dev secret in source |
| **Sensitive data in current repo?** | **Yes** — SQLite DB (11 MB) with stock/trade data; hardcoded default secret key |
| **Sensitive data in git history?** | **Yes** — database binary blobs persist across 8+ commits; no real API keys found |

---

## B. Findings

### CONFIRMED Findings

---

#### B1. SQLite database files tracked in git
- **Severity**: HIGH
- **Status**: **Remediated** — `.gitignore` patterns added and `git rm --cached` executed. Optional history rewrite (BFG) still recommended before going public.
- **Files**: `data/stock_screener.db` (11.3 MB), `data/stock_screener.db-shm` (32 KB), `data/stock_screener.db-wal` (148 KB)
- **Evidence**: `git ls-files` shows all three tracked. Binary diffs present in 8+ commits since initial commit `0bdbc36`.
- **Attack/exposure scenario**: Anyone cloning the repo gets the full database containing stock data, computed metrics, and any trade records (entry/exit prices, PnL, brokerage positions). The WAL file may contain recently-written but uncommitted transaction data.
- **Remediation**: (1) Add `data/*.db`, `data/*.db-shm`, `data/*.db-wal`, `data/*.db-journal` to `.gitignore`. (2) `git rm --cached data/stock_screener.db*`. (3) Rewrite git history with BFG Repo Cleaner to remove all historical copies.
- **Requires git history rewrite?** Yes — 11 MB of binary blobs persist in pack files forever otherwise.
- **Requires secret rotation?** No.

---

#### B2. Hardcoded default JWT secret key
- **Severity**: HIGH
- **Status**: **Remediated** — default replaced with `secrets.token_hex(32)` factory.
- **File**: `src/config.py`, line 82
- **Evidence**: `secret_key: str = "dev-secret-change-in-production"`
- **Attack/exposure scenario**: If auth is implemented using this default key (and the user doesn't set `SECRET_KEY` in `.env`), any attacker who reads the source can forge JWT tokens. The value is also in `.env_template.example` as a placeholder, which is fine — the problem is the in-code default.
- **Remediation**: Remove the default value. Either fail at startup if `SECRET_KEY` is not set, or generate a random key at startup for local dev (e.g., `secrets.token_hex(32)`).
- **Requires git history rewrite?** No — it's a placeholder, not a real secret. But the pattern should be fixed before auth is wired up.
- **Requires secret rotation?** No (not a real secret today, but must be fixed before auth goes live).

---

#### B3. No authentication or authorization on any API endpoint
- **Severity**: HIGH
- **Status**: **Remediated** — `require_admin` API key guard added to all admin/destructive endpoints. Dev mode bypasses for local use. See `docs/99_security/dev-security-guide.md`.
- **Files**: `src/api/main.py`, all files in `src/api/routers/`
- **Evidence**: Zero auth dependencies (`Depends(...)`) on any endpoint. JWT libraries (`python-jose`, `passlib`) are in `requirements.txt` but never imported or used. `src/api/deps.py` only provides `get_db`.
- **Attack/exposure scenario**: Every endpoint is publicly accessible, including destructive operations:
  - `DELETE /admin/ticker/{sym}` — cascade-deletes all data for a ticker
  - `POST /admin/fetch`, `POST /admin/compute` — triggers expensive ingestion/computation
  - `POST /api/trades/import`, `POST /api/trades/import-brokerage` — bulk-imports trades
  - `DELETE /api/trades/{id}` — deletes trades
  - `POST /api/scanner/trigger` — triggers resource-intensive background scans
- **Remediation**: Implement auth middleware before any network exposure. At minimum, add API key auth for admin endpoints.
- **Requires git history rewrite?** No.
- **Requires secret rotation?** No.

---

#### B4. `.gitignore` missing critical entries
- **Severity**: HIGH
- **Status**: **Remediated** — all missing patterns added to `.gitignore`.
- **File**: `.gitignore`
- **Evidence**: Has Django-default `db.sqlite3` but not the actual patterns this project uses. Missing entries for:
  - `data/*.db`, `data/*.db-shm`, `data/*.db-wal`, `data/*.db-journal`
  - `data/scanner/` (cache files — `universe_cache.json` is tracked)
  - `data/technical_chart/` (generated chart data — `BB_day_trade.json` is tracked)
  - `.claude/settings.local.json` (IDE-specific permissions)
  - `*.bmp` (7 planning images tracked under `plan/`)
- **Attack/exposure scenario**: Every `git add .` or `git add -A` will re-add database and cache files.
- **Remediation**: Add all missing patterns (see Section E).
- **Requires git history rewrite?** No (but tracked files need `git rm --cached`).

---

#### B5. User-controlled `sort_by` parameter flows into `getattr()` on ORM model
- **Severity**: MEDIUM
- **Status**: **Remediated** — `sort_by` validated against explicit allowlist; invalid values fall back to `gross_margin`.
- **File**: `src/metrics.py`, line ~840; `src/api/routers/screener.py`, line ~128
- **Evidence**: `sort_col = getattr(MetricsQuarterly, sort_by, MetricsQuarterly.gross_margin)` — `sort_by` comes directly from query string.
- **Attack/exposure scenario**: Attacker can pass attribute names like `__class__`, `metadata`, `__dict__` to probe internal model structure. SQLAlchemy would likely reject non-column attributes in `.order_by()`, but the pattern is unsafe.
- **Remediation**: Validate `sort_by` against an explicit allowlist of column names before calling `getattr()`.
- **Requires git history rewrite?** No.

---

#### B6. No rate limiting on any endpoint
- **Severity**: MEDIUM
- **Status**: **Remediated** — `slowapi` added with global 120/min default + tighter per-endpoint limits on admin/scanner.
- **Files**: `src/api/main.py`, all routers
- **Evidence**: No `slowapi`, no custom middleware, no rate-limit logic anywhere.
- **Attack/exposure scenario**: Repeated calls to `POST /admin/compute` or `POST /api/scanner/trigger` cause resource exhaustion (CPU, network to yfinance, SQLite locks).
- **Remediation**: Add `slowapi` or equivalent rate limiter, especially on admin and scanner endpoints.

---

#### B7. `POST /api/trades/import` accepts `list[dict]` with no schema validation
- **Severity**: MEDIUM
- **Status**: **Remediated** — replaced with `list[TradeImportRow]` Pydantic model with field constraints.
- **File**: `src/api/routers/trades.py`, line ~193-200
- **Evidence**: Endpoint type is `list[dict]` — no Pydantic model at the API boundary.
- **Attack/exposure scenario**: Malformed or oversized payloads are not rejected at the boundary. The service layer validates individual fields, but the API accepts any JSON structure.
- **Remediation**: Define a Pydantic model for import rows and use `list[TradeImportRow]` instead of `list[dict]`.

---

#### B8. No size limit on brokerage CSV import payload
- **Severity**: MEDIUM
- **Status**: **Remediated** — `csv_text` now has `max_length=10_000_000`.
- **File**: `src/api/schemas.py`, line ~683
- **Evidence**: `csv_text: str` with no `max_length` constraint.
- **Attack/exposure scenario**: Multi-gigabyte string payload causes memory exhaustion.
- **Remediation**: Add `Field(max_length=10_000_000)` or similar to `BrokerageImportRequest.csv_text`.

---

#### B9. Database URL logged at startup
- **Severity**: MEDIUM
- **Status**: **Remediated** — URL now passed through `make_url().render_as_string(hide_password=True)`.
- **File**: `src/database.py`, line ~74
- **Evidence**: `logger.info("Database engine created: %s", url)`
- **Attack/exposure scenario**: If the user switches from SQLite to PostgreSQL with credentials in the URL, the full connection string (including password) appears in logs.
- **Remediation**: Mask or redact credentials from the logged URL.

---

#### B10. Trade data accessible without user scoping
- **Severity**: MEDIUM
- **Status**: **Deferred** — requires a full user-authentication system; not a quick fix. Tracked in dev-security-guide.md deferred items table.
- **File**: `src/api/routers/trades.py`
- **Evidence**: All trade endpoints default to `user_id="default"`. No auth, no user isolation.
- **Attack/exposure scenario**: All trade data (positions, PnL, brokerage imports) is accessible to anyone reaching the API.
- **Remediation**: Implement user authentication and derive `user_id` from the authenticated session.

---

#### B11. Runtime/cache data files tracked in git
- **Severity**: LOW
- **Status**: **Remediated** — `git rm --cached` executed for `data/scanner/universe_cache.json` and `data/technical_chart/BB_day_trade.json`. `.gitignore` patterns were already in place. `custom_etf_tickers.json` intentionally kept tracked.
- **Files**: `data/scanner/universe_cache.json`, `data/technical_chart/BB_day_trade.json`, `data/custom_etf_tickers.json`
- **Evidence**: `git ls-files` shows these tracked.
- **Attack/exposure scenario**: Cache files may contain environment-specific data and will cause unnecessary merge conflicts. `custom_etf_tickers.json` may be intentionally tracked.
- **Remediation**: Add `data/scanner/` and `data/technical_chart/` to `.gitignore`; `git rm --cached` for the files. Decide if `custom_etf_tickers.json` should be tracked or templated.

---

#### B12. CORS allows wildcard methods and headers
- **Severity**: LOW
- **Status**: **Remediated** — restricted to specific methods and headers.
- **File**: `src/api/main.py`, lines ~61-62
- **Evidence**: `allow_methods=["*"]`, `allow_headers=["*"]`, `allow_credentials=True`
- **Attack/exposure scenario**: Origins are correctly restricted to localhost. Wildcards are overly permissive but low risk for a local-only app.
- **Remediation**: Restrict to `["GET", "POST", "PUT", "DELETE"]` and the specific headers used.

---

#### B13. Swagger/ReDoc docs enabled by default
- **Severity**: LOW
- **Status**: **Remediated** — docs disabled when `DEV_MODE=false`.
- **File**: `src/api/main.py`, lines ~46-47
- **Evidence**: `docs_url="/docs"`, `redoc_url="/redoc"`
- **Attack/exposure scenario**: Full API schema exposed. Fine for development; should be disabled in production.
- **Remediation**: Disable or auth-gate docs in production.

---

#### B14. Dependencies use `>=` without upper bounds
- **Severity**: LOW
- **Status**: **Remediated** — `requirements.lock` generated with exact pinned versions for reproducible deployments.
- **File**: `requirements.txt`
- **Evidence**: All deps use `>=` minimum versions only.
- **Attack/exposure scenario**: Future `pip install` could pull breaking or vulnerable versions.
- **Remediation**: Generate a `requirements.lock` or pin exact versions for production.

---

#### B15. Unused auth libraries in dependencies
- **Severity**: LOW (informational)
- **Status**: **Remediated** — `python-jose[cryptography]` and `passlib[bcrypt]` removed from `requirements.txt`.
- **File**: `requirements.txt`
- **Evidence**: `python-jose[cryptography]>=3.3.0`, `passlib[bcrypt]>=1.7.4` listed but never imported.
- **Attack/exposure scenario**: Adds unused attack surface. Minor.
- **Remediation**: Remove until auth is implemented, or implement auth.

---

#### B16. BMP image files tracked (7 files)
- **Severity**: LOW
- **Status**: **Remediated** — `*.bmp` added to `.gitignore` and all 7 files removed from tracking via `git rm --cached`.
- **Files**: `plan/*.bmp` (7 files)
- **Evidence**: Uncompressed bitmap files used for planning screenshots.
- **Attack/exposure scenario**: Repository bloat. May contain UI screenshots showing data.
- **Remediation**: Convert to PNG or exclude from tracking.

---

#### B17. Dynamic SQL in migration code
- **Severity**: LOW
- **Status**: **Remediated** — security comment added to `_migrate_columns()`.
- **File**: `src/database.py`, line ~155
- **Evidence**: `conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))` — inputs come from hardcoded `_NEW_COLUMNS` list, not user input.
- **Attack/exposure scenario**: Not exploitable today. Would become a vector if `_NEW_COLUMNS` were ever populated from external input.
- **Remediation**: No action needed now. Add a comment noting that the inputs must remain hardcoded.

---

### Negative Findings (No Issues)

| Check | Result |
|-------|--------|
| `.env` file ever committed | No — never in any commit |
| Real API keys in history | No — only placeholders like `your_fred_api_key_here` |
| `sk-` (OpenAI), `ghp_` (GitHub), `Bearer` tokens | No matches |
| `.pem`, `.key`, `.p12`, `.pfx` files | Never committed |
| `pickle.load`, `yaml.load`, `eval()`, `exec()` | Not found |
| XSS via `dangerously_allow_html` | Not found — Dash auto-escapes |
| `__pycache__` tracked | No |
| Log files tracked | No |
| Notebooks with output tracked | No |
| Personal paths (`C:\Users\...`) in source | No |
| Dash debug mode | Off by default (`dash_debug: bool = False`) |

---

## C. Immediate Next Steps (This Week)

1. ~~**Update `.gitignore`**~~ — **Done.** All missing patterns added.

2. ~~**Remove tracked files that should be ignored**~~ — **Done.** `git rm --cached` executed for all database, cache, and BMP files.

3. **Decide on git history rewrite**: The 11 MB database has been in ~8 commits. If this repo is already shared or will be made public:
   ```bash
   # Install BFG Repo Cleaner, then:
   bfg --delete-files "*.db" --delete-files "*.db-shm" --delete-files "*.db-wal"
   git reflog expire --expire=now --all && git gc --prune=now --aggressive
   # Force-push all branches (coordinate with any collaborators)
   ```

4. ~~**Fix the default secret key**~~ — **Done.** `secrets.token_hex(32)` generated per startup.

5. ~~**Add `sort_by` allowlist**~~ — **Done.** Validated against explicit column set.

6. ~~**Add input validation** to `POST /api/trades/import`~~ — **Done.** `list[TradeImportRow]` Pydantic model.

7. ~~**Add `max_length`** to `BrokerageImportRequest.csv_text`~~ — **Done.** 10 MB limit.

8. ~~**Mask database URL in logs**~~ — **Done.** Credentials redacted via `hide_password=True`.

---

## D. Before-Production Checklist

| # | Control | Status | Priority |
|---|---------|--------|----------|
| 1 | Authentication on all endpoints (at minimum API key for admin) | **Done** — API key guard on admin/destructive endpoints via `require_admin` dep; dev mode bypass for local use | CRITICAL |
| 2 | Authorization / user scoping for trade data | Missing — requires full user auth system | CRITICAL |
| 3 | Rate limiting (especially admin, scanner, compute) | **Done** — `slowapi` global 120/min + tighter per-endpoint limits on admin/scanner | HIGH |
| 4 | Secret key required from environment (no default) | **Done** — `secrets.token_hex(32)` generated per startup if not set | HIGH |
| 5 | Disable Swagger/ReDoc in production or gate behind auth | **Done** — disabled when `DEV_MODE=false` | HIGH |
| 6 | HTTPS termination (reverse proxy or cloud LB) | Missing — infrastructure concern | HIGH |
| 7 | Input validation on all API boundaries (Pydantic models) | **Done** — `TradeImportRow` model replaces `list[dict]`; `sort_by` allowlist added | HIGH |
| 8 | Request body size limits | **Done** — `BrokerageImportRequest.csv_text` has `max_length=10_000_000` | MEDIUM |
| 9 | Database credential masking in logs | **Done** — `make_url().render_as_string(hide_password=True)` in `database.py` | MEDIUM |
| 10 | Dependency version pinning / lockfile | **Done** — `requirements.lock` with exact pins | MEDIUM |
| 11 | CORS restrict methods/headers to actual usage | **Done** — restricted to specific methods and headers | LOW |
| 12 | Security headers (HSTS, CSP, X-Frame-Options) | **Done** — `SecurityHeadersMiddleware` added; CSP in production mode | LOW |
| 13 | Structured logging with PII filtering | Missing | LOW |
| 14 | Dependency vulnerability scanning (pip-audit, safety) | Missing | LOW |
| 15 | Container / process isolation for deployment | Missing | LOW |

---

## E. Patch Suggestions

### E1. `.gitignore` additions

Add the following block to the end of `.gitignore`:

```gitignore
# === Project-specific ===

# SQLite database files
data/*.db
data/*.db-shm
data/*.db-wal
data/*.db-journal

# Generated/cached runtime data
data/scanner/
data/technical_chart/

# Planning images (use PNG if needed in repo)
*.bmp

# Claude Code local settings
.claude/settings.local.json
```

### E2. `.env.example` (proposed contents)

Rename `.env_template.example` to `.env.example` (standard convention) with contents:

```env
# === Required ===
SECRET_KEY=          # REQUIRED — generate with: python -c "import secrets; print(secrets.token_hex(32))"

# === API Keys (optional — features degrade gracefully without them) ===
FRED_API_KEY=        # https://fred.stlouisfed.org/docs/api/api_key.html
NEWSAPI_KEY=         # https://newsapi.org/register
FINNHUB_API_KEY=     # https://finnhub.io/register
ALPHAVANTAGE_API_KEY=# https://www.alphavantage.co/support/#api-key

# === Server Configuration (defaults shown) ===
API_HOST=127.0.0.1
API_PORT=8000
DASH_HOST=127.0.0.1
DASH_PORT=8050
DASH_DEBUG=false

# === Database (default: SQLite in data/) ===
DATABASE_URL=sqlite:///data/stock_screener.db
```

### E3. Config restructuring suggestion

In `src/config.py`, change the secret key handling:

```python
# BEFORE (current)
secret_key: str = "dev-secret-change-in-production"

# AFTER (safe)
secret_key: str = Field(default_factory=lambda: __import__('secrets').token_hex(32))
# This generates a random key per startup if not set in .env.
# For production, always set SECRET_KEY in environment.
```

### E4. Safer local development workflow

1. After cloning, copy `.env.example` to `.env` and fill in values.
2. Never commit `data/` contents — the database is auto-created on first run.
3. Run `git status` before committing to verify no database/cache files are staged.
4. For shared development, provide a `scripts/seed_data.py` or document how to populate data, rather than sharing the database file.

---

## Appendix: Severity Definitions

| Severity | Meaning |
|----------|---------|
| CRITICAL | Immediate exploitation risk; real secrets exposed |
| HIGH | Significant risk if repo is public or app is network-accessible |
| MEDIUM | Should be fixed before any non-localhost deployment |
| LOW | Best practice gap; fix when convenient |
