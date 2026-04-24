# Rate Limiting Configuration

This document covers all rate-limiting knobs in the codebase. Review and tighten
these values before any public deployment.

---

## 1. API Rate Limits (slowapi)

**Source:** `src/api/rate_limit.py` and individual routers under `src/api/routers/`

These limits are enforced per IP address using the [slowapi](https://github.com/laurentS/slowapi) library.
Exceeding a limit returns `HTTP 429 Too Many Requests`.

| Scope | Current (dev) | Recommended (prod) | File |
|-------|---------------|--------------------|------|
| Global default | 600/minute | 60/minute | `src/api/rate_limit.py` |
| `POST /admin/fetch` | 60/minute | 5/minute | `src/api/routers/admin.py` |
| `POST /admin/compute` | 60/minute | 3/minute | `src/api/routers/admin.py` |
| `POST /admin/classify` | 60/minute | 3/minute | `src/api/routers/admin.py` |
| `DELETE /admin/ticker/{sym}` | 60/minute | 10/minute | `src/api/routers/admin.py` |
| `POST /api/scanner/trigger` | 60/minute | 3/minute | `src/api/routers/scanner.py` |

### How to change

`src/api/rate_limit.py` — global default:
```python
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
```

Per-endpoint limits use the `@limiter.limit(...)` decorator directly above the route function.
Example in `src/api/routers/scanner.py`:
```python
@limiter.limit("3/minute")
def trigger_scan(request: Request, ...):
```

### Future improvement
Consider keying limits by authenticated user/role instead of IP so that
legitimate admin users are not throttled by shared-IP environments (VPN, office NAT).
See slowapi docs: [custom key functions](https://slowapi.readthedocs.io/en/latest/#custom-key-function).

---

## 2. yfinance OHLCV Fetch Throttle

**Source:** `src/scanner/orchestrator.py` (lines ~41-43)

The scanner uses `yf.download()` to fetch OHLCV data for all tickers in bulk
(one HTTP call per chunk), which is far faster than individual per-ticker requests.
A small pause between chunks avoids triggering Yahoo Finance throttling.

| Setting | Current (dev) | Recommended (prod) | Description |
|---------|---------------|--------------------|-------------|
| `_DOWNLOAD_CHUNK_SIZE` | 100 | 50–100 | Tickers per `yf.download` call |
| `_DOWNLOAD_CHUNK_PAUSE` | 0.5s | 1.0–2.0s | Pause between chunks |

### How to change

```python
# src/scanner/orchestrator.py
_DOWNLOAD_CHUNK_SIZE  = 100  # tickers per yf.download call
_DOWNLOAD_CHUNK_PAUSE = 0.5  # seconds between chunks
```

### Estimated scan time (361 tickers)

| Profile | Chunk size | Chunk pause | Est. chunks | Est. sleep time |
|---------|------------|-------------|-------------|-----------------|
| Dev (current) | 100 | 0.5s | 4 | ~1.5s sleep + network |
| Prod (recommended) | 50 | 1.5s | 8 | ~10s sleep + network |

Network time dominates: a single `yf.download` for 100 tickers typically takes
3–8 seconds depending on connection and Yahoo latency. Total OHLCV fetch for
~360 tickers should complete in **15–30 seconds** in dev.

### Notes
- `yf.download` fetches all tickers in a chunk with `threads=True` (parallel
  internally), so chunk size has a bigger impact than the pause.
- If Yahoo starts returning empty results or connection errors mid-scan, reduce
  `_DOWNLOAD_CHUNK_SIZE` to 50 and increase `_DOWNLOAD_CHUNK_PAUSE` to 2.0s.
- Single-ticker downloads return a flat DataFrame; multi-ticker downloads return
  a MultiIndex `(field, ticker)`. The orchestrator handles both cases automatically.
- Delisted or unavailable tickers will silently produce `None` in the results map
  and are skipped during signal detection.
