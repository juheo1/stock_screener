# OHLCV Data Architecture: Server Mode Plan

**Current state**: All OHLCV data is stored as local Parquet files under
`data/ohlcv/` and fetched directly from yfinance on the developer's machine.
The intraday monitor polls yfinance from the same machine.

**Planned direction**: Centralise OHLCV storage and data ingestion on a
dedicated server so that multiple client machines share one data source,
never call yfinance directly, and can be upgraded to a paid streaming feed
without touching client code.

This is Phase 5 of the roadmap defined in `plan/ohlcv_cache_layer_plan.md`.
Phases 1–4 (local cache, intraday archival, intraday monitor, cache-first
frontend reads) have been implemented and must be stable before this phase
begins.

---

## Why centralise

| Problem with local-only mode | Impact |
|-------------------------------|--------|
| Each dev machine runs its own intraday monitor | Duplicate yfinance polling; different machines see different signal histories |
| yfinance rate limits per IP | Parallel machines get throttled |
| Intraday archive lives only on one machine | Cannot share backtests across devices |
| No path to a paid data provider | Would need changes on every client |
| Adding a second user requires duplicating all data | Blocks the multi-user website plan |

---

## Target architecture

```
                        ┌────────────────────────────────┐
                        │         Data Server            │
                        │                                │
                        │  ┌─────────────────────────┐  │
                        │  │  Intraday Monitor        │  │
                        │  │  (single process)        │  │
                        │  │  Polls yfinance / paid   │  │
                        │  │  provider on schedule    │  │
                        │  └──────────┬──────────────┘  │
                        │             │                  │
                        │  ┌──────────▼──────────────┐  │
                        │  │  OHLCV Store             │  │
                        │  │  (Parquet on SSD or S3)  │  │
                        │  └──────────┬──────────────┘  │
                        │             │                  │
                        │  ┌──────────▼──────────────┐  │
                        │  │  FastAPI OHLCV endpoints │  │
                        │  │  /api/ohlcv/daily/{t}    │  │
                        │  │  /api/ohlcv/intraday/..  │  │
                        │  │  /api/ohlcv/live/{t}     │  │
                        │  └─────────────────────────┘  │
                        └───────────────┬────────────────┘
                                        │ HTTP / LAN
                          ┌─────────────┼─────────────┐
                          │             │             │
               ┌──────────▼──┐  ┌───────▼───┐  ┌────▼──────┐
               │  Dev laptop │  │  Dash UI  │  │  Future   │
               │  scanner    │  │  (charts) │  │  client N │
               └─────────────┘  └───────────┘  └───────────┘
```

The data server is the sole writer to OHLCV storage. All clients read via
the HTTP API — they never call yfinance and never write parquet files.

---

## Storage options

| Option | Best for | Notes |
|--------|----------|-------|
| Local SSD (same VPS as API) | Small scale (1–10 users) | Simplest; no egress cost |
| Network-attached SSD (NAS) | Dev-home multi-machine | rsync-able; cheap |
| S3 / R2 / GCS | Cloud deployment | Pay-per-read but globally accessible; use `s3fs` or `boto3` in OHLCVStore |
| TimescaleDB | High query volume | SQL-queryable time-series; replaces Parquet if needed |

For the immediate near-term, a single VPS with an SSD is sufficient.

---

## New API endpoints (data server)

These would live in a new router `src/api/routers/ohlcv.py`:

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/ohlcv/daily/{ticker}` | Return daily DataFrame as JSON or Parquet bytes |
| `GET` | `/api/ohlcv/intraday/{interval}/{ticker}` | Return intraday archive for a date range |
| `GET` | `/api/ohlcv/live/{ticker}` | Return today's in-progress 1m bars |
| `GET` | `/api/ohlcv/meta/{ticker}` | Return last-updated timestamps |
| `POST` | `/api/ohlcv/sync` | Trigger an incremental sync (admin only) |
| `GET` | `/api/ohlcv/tickers` | List tickers with cached data |

Response format options:
- **JSON** — easy for small payloads; use `df.to_dict(orient="split")`
- **Parquet bytes** — efficient for large date ranges; client does
  `pd.read_parquet(io.BytesIO(response.content))`

Clients should request Parquet for anything over ~100 bars and JSON for
live status / small intraday slices.

---

## Client-side changes

### `OHLCVStore` abstraction

The client-side `OHLCVStore` (currently reads local Parquet) would grow an
HTTP backend variant:

```python
# Pseudocode — not yet implemented
class RemoteOHLCVStore(OHLCVStore):
    """Read-only OHLCVStore that fetches from the data server API."""

    def __init__(self, server_url: str, api_key: str | None = None) -> None:
        self.server_url = server_url.rstrip("/")
        self._session   = requests.Session()
        if api_key:
            self._session.headers["X-API-Key"] = api_key

    def read_daily(self, ticker: str) -> pd.DataFrame | None:
        resp = self._session.get(
            f"{self.server_url}/api/ohlcv/daily/{ticker}",
            params={"format": "parquet"},
        )
        if not resp.ok:
            return None
        return pd.read_parquet(io.BytesIO(resp.content))

    # ... intraday and live methods follow the same pattern
```

`OHLCVFetcher` on clients would still exist but call `RemoteOHLCVStore`
instead of writing locally. The scanner and strategy data module are
unchanged because they depend on the `OHLCVStore` interface, not its
implementation.

To switch a deployment from local to server mode, set one environment
variable:

```
# .env
OHLCV_MODE=remote
OHLCV_SERVER_URL=http://192.168.1.50:8000
OHLCV_SERVER_API_KEY=<key>
```

`src/ohlcv/__init__.py` would expose a factory function `get_store()` that
reads `OHLCV_MODE` and returns either the local `OHLCVStore` or the
`RemoteOHLCVStore`.

---

## Data source upgrade path

`OHLCVFetcher.fetch_live_bars()` currently calls yfinance. When latency
becomes a bottleneck, swap the data source behind this one method:

| Provider | Latency | Cost | Integration effort |
|----------|---------|------|--------------------|
| yfinance (current) | 60–120 s | Free | Done |
| Polygon.io REST | 15–30 s | ~$30/mo | Low — same interface |
| Alpaca websocket | Sub-second | $0 (paper), ~$30/mo (live) | Medium — async streaming |
| IEX Cloud | 15 s | ~$9/mo | Low — REST |

All providers return the same OHLCV columns so only `fetch_live_bars()` in
`OHLCVFetcher` needs to change.  The monitor, strategies, and frontend are
unchanged.

---

## Storage sizing

At 400 tickers, expected disk usage on the data server:

| Data type | Size |
|-----------|------|
| Daily (max history, 400 tickers) | ~150 MB (20+ years per ticker) |
| 1min archive (1yr, 400 tickers) | ~2 GB |
| 5min archive (1yr, 400 tickers) | ~480 MB |
| **Total** | **~2.6 GB** |

At 2 000 tickers: ~13 GB. A $6/mo VPS with 25 GB SSD handles this easily.

> **Note**: Daily bars are fetched with `period="max"` (full yfinance history).
> The first full-refresh run will be slower than previous 2-year fetches but
> subsequent nightly syncs remain fast (incremental 5-day delta).

For S3/R2 storage: ~$0.05/GB/month, so full archive = ~$0.65/month plus
per-request costs (negligible for read patterns here).

---

## Relationship to the multi-user website plan

See `docs/98_deployment/website-deployment-requirements.md` for the full
multi-user deployment plan.  The OHLCV server is an independent concern
that can be deployed before or after user auth:

- **Before auth**: data server on a home NAS; all dev machines share one
  intraday monitor. Low effort, immediate benefit.
- **With auth (Phase 3 of website plan)**: data server co-located with the
  FastAPI app on the production VPS. OHLCV endpoints sit behind the same
  API key / tier-check middleware as the rest of the API.

The OHLCV server does not require PostgreSQL, Stripe, or any user-auth
machinery — it is purely a data infrastructure concern.

---

## Migration checklist

- [ ] Implement `RemoteOHLCVStore` with Parquet-over-HTTP transport
- [ ] Add `OHLCV_MODE` config flag and `get_store()` factory in `src/ohlcv/__init__.py`
- [ ] Add `src/api/routers/ohlcv.py` (read endpoints + admin sync trigger)
- [ ] Register `ohlcv` router in `src/api/main.py`
- [ ] Move intraday monitor to server (single process; remove from client startup)
- [ ] Add `OHLCV_SERVER_URL` / `OHLCV_SERVER_API_KEY` to `.env.example`
- [ ] Update `docs/00_getting_started/` quickstart to note server vs local modes
- [ ] Optional: add S3 backend to `OHLCVStore` (`_write_parquet` / `_read_parquet` abstraction)
- [ ] Optional: upgrade `fetch_live_bars()` to paid provider (Polygon / Alpaca)
