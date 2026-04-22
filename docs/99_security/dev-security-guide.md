# Developer Security Guide

## Overview

The stock screener separates **regular (read-only) access** from
**admin (destructive) access** using an API-key gate controlled by the
`DEV_MODE` environment variable.

| Setting | Dev mode (`DEV_MODE=true`, default) | Production mode (`DEV_MODE=false`) |
|---------|------------------------------------|-------------------------------------|
| Admin endpoints | Open — no key required | Require `X-Admin-API-Key` header |
| Read-only endpoints | Open | Open |
| Swagger / ReDoc | Enabled at `/docs`, `/redoc` | Disabled (404) |
| Secret key | Auto-generated per startup | Must be set via `SECRET_KEY` env var |
| Rate limiting | Active (lenient defaults) | Active (same limits) |
| Security headers | Partial (no CSP) | Full (CSP, X-Frame-Options, etc.) |

---

## Quick start — local development

Run the server in its default dev mode:

```bash
python scripts/run_server.py
```

Everything works out of the box:

- All API endpoints are accessible without authentication.
- Swagger UI is available at `http://127.0.0.1:8000/docs`.
- A random `SECRET_KEY` is generated on each startup (fine for local use).
- The Dash frontend at `http://127.0.0.1:8050` calls the API without any
  API-key headers.

No `.env` changes are needed for local dev beyond the optional
`FRED_API_KEY` for macro data.

---

## How regular vs admin access works

### Regular user (read-only)

Any client that can reach the API may call **read-only** endpoints without
credentials.  These include:

| Category | Example endpoints |
|----------|-------------------|
| Screener | `GET /screener`, `GET /presets` |
| Dashboard | `GET /dashboard` |
| Comparison | `POST /compare` |
| Retirement | `POST /retirement` |
| Metals | `GET /metals`, `GET /metals/{id}/history` |
| Macro | `GET /macro`, `GET /macro/{series_id}` |
| Scanner results | `GET /api/scanner/results`, `GET /api/scanner/status` |
| Trade listing | `GET /api/trades/`, `GET /api/trades/strategies` |
| News / Sentiment / Calendar | various `GET` endpoints |

These endpoints never modify or delete data.

### Admin / developer (destructive)

Endpoints that **create, modify, or delete** data are gated behind the
`require_admin` dependency.  In dev mode the gate is open; in production it
requires the `X-Admin-API-Key` header.

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/admin/fetch` | Fetch financial statements |
| POST | `/admin/compute` | Recompute metrics |
| POST | `/admin/classify` | Rerun zombie classification |
| POST | `/admin/refresh/macro` | Refresh FRED macro data |
| POST | `/admin/refresh/comex` | Refresh COMEX inventory |
| POST | `/admin/refresh/metals` | Refresh metals prices |
| GET | `/admin/tickers` | List tracked tickers |
| DELETE | `/admin/ticker/{sym}` | Remove a ticker (cascade delete) |
| DELETE | `/api/trades/{id}` | Delete a trade |
| POST | `/api/trades/import` | Bulk-import trades |
| POST | `/api/trades/import-brokerage` | Import brokerage CSV |
| POST | `/api/scanner/trigger` | Trigger a background scan |

### How the gate works (`src/api/deps.py`)

```
DEV_MODE=true   →  all requests pass through (no key check)
DEV_MODE=false  →  X-Admin-API-Key header must match ADMIN_API_KEY env var
                    missing ADMIN_API_KEY → 500 (fail-closed)
                    wrong/missing key    → 403 Forbidden
```

The Dash frontend does **not** send API-key headers.  In production, admin
operations should be run via CLI scripts or `curl` with the header — not
through the UI.

---

## Production mode

To run the server exposed on a network, set these in `.env`:

```env
DEV_MODE=false
SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
ADMIN_API_KEY=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
```

### What changes in production mode

1. **Admin endpoints are locked.**  Requests without a valid
   `X-Admin-API-Key` header receive `403 Forbidden`.

2. **Swagger / ReDoc are disabled.**  `/docs` and `/redoc` return 404.

3. **Content-Security-Policy header is added.**  Restricts script/style
   sources to `'self'`.

4. **`SECRET_KEY` must be stable.**  If you rely on JWT tokens or signed
   sessions, the key must persist across restarts.

5. **If `ADMIN_API_KEY` is not set** while `DEV_MODE=false`, admin
   endpoints return `500 Internal Server Error` (fail-closed — no
   accidental open access).

---

## Calling admin endpoints in production

Include the API key header:

```bash
curl -X POST http://127.0.0.1:8000/admin/compute \
  -H "Content-Type: application/json" \
  -H "X-Admin-API-Key: your-key-here" \
  -d '{}'
```

---

## Rate limiting

Rate limits are enforced on all endpoints via `slowapi`:

| Scope | Limit |
|-------|-------|
| Global default | 120 requests/minute per IP |
| `POST /admin/fetch` | 5/minute |
| `POST /admin/compute` | 3/minute |
| `POST /admin/classify` | 3/minute |
| `DELETE /admin/ticker/{sym}` | 10/minute |
| `POST /api/scanner/trigger` | 3/minute |

Exceeding a limit returns `429 Too Many Requests`.

---

## Security headers

The API injects these headers on **every response**:

| Header | Value | Notes |
|--------|-------|-------|
| `X-Content-Type-Options` | `nosniff` | Always |
| `X-Frame-Options` | `DENY` | Always |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Always |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` | Always |
| `Content-Security-Policy` | `default-src 'self'; ...` | Production only |

---

## Dependency management

- **`requirements.txt`** — minimum version bounds (`>=`) for development.
- **`requirements.lock`** — exact pinned versions from a known-good
  environment.  Use this for reproducible deployments:

  ```bash
  pip install -r requirements.lock
  ```

  Regenerate after upgrading packages:

  ```bash
  pip freeze > requirements.lock
  ```

---

## Security checklist for new deployments

- [ ] Set `DEV_MODE=false` in `.env`
- [ ] Set a strong `SECRET_KEY` (64+ hex chars)
- [ ] Set a strong `ADMIN_API_KEY` (64+ hex chars)
- [ ] Verify `/docs` returns 404
- [ ] Verify admin endpoints return 403 without the API key header
- [ ] Place behind a reverse proxy with HTTPS (nginx, Caddy, etc.)
- [ ] Do not commit `.env` or `data/*.db` to git
- [ ] Run `pip-audit` or `safety check` against `requirements.txt`
- [ ] Use `requirements.lock` for pinned dependencies

---

## What is intentionally deferred

| Item | Reason |
|------|--------|
| Per-user authentication & trade scoping (B10) | Requires a full user-auth system; trades currently use `user_id="default"` |
| HTTPS termination | Infrastructure concern — use a reverse proxy (nginx, Caddy) |
| Git history rewrite for database blobs | Destructive; coordinate with collaborators before running BFG |
| Container / process isolation | Deployment-time concern, not app code |
