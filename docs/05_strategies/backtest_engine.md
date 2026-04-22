# Backtest Engine

**Module**: `frontend/strategy/backtest.py`

Both the Technical Chart page and the Strategy Scanner call `run_backtest()`.
Each UI page decides independently which fields to display.

---

## Purpose and Scope

The backtest engine simulates strategy trades on historical OHLCV data and
returns a frozen summary dataclass. It does **not**:
- Apply slippage or commissions
- Implement position sizing (one unit per trade assumed for P&L; full
  reinvestment assumed for compounded return)
- Simulate partial fills or market impact

---

## Input Contract

```python
run_backtest(
    df:              pd.DataFrame,          # OHLCV, DatetimeIndex, must contain "Close"
    signals:         pd.Series | np.ndarray,# +1 / -1 / 0, aligned to df
    *,
    spy_df:          pd.DataFrame | None = None,  # SPY OHLCV for benchmark
    initial_capital: float = 1_000.0,       # seed for compounded return
) -> BacktestResult
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `df` | `pd.DataFrame` | OHLCV data with `DatetimeIndex`. Must contain a `Close` column. |
| `signals` | array-like | Signal series aligned to `df`. `1` = enter long / exit short. `-1` = enter short / exit long. `0` = hold. |
| `spy_df` | `pd.DataFrame \| None` | Optional SPY OHLCV for buy-and-hold benchmark comparison. Pass `None` to skip benchmark. |
| `initial_capital` | `float` | Starting capital for the compounded return calculation. Default `$1 000`. |

---

## Position State Machine

The engine processes signals sequentially with one position at a time (no pyramiding):

```
State: FLAT
  Signal +1  →  enter LONG  (record entry price + date)
  Signal -1  →  enter SHORT (record entry price + date)
  Signal  0  →  stay FLAT

State: LONG
  Signal -1  →  exit LONG, record trade, return to FLAT
  Signal +1  →  ignored (already long)
  Signal  0  →  hold

State: SHORT
  Signal +1  →  exit SHORT, record trade, return to FLAT
  Signal -1  →  ignored (already short)
  Signal  0  →  hold
```

Open positions at the end of the data are **not closed and not included** in
the trade list.

---

## Trade Record Schema

Each completed round-trip produces one dict in `BacktestResult.trades`:

| Field | Type | Description |
|-------|------|-------------|
| `entry_date` | `str` | ISO date of entry bar (`"YYYY-MM-DD"`) |
| `exit_date` | `str` | ISO date of exit bar |
| `entry_price` | `float` | `Close` price at entry bar |
| `exit_price` | `float` | `Close` price at exit bar |
| `pnl` | `float` | Price-point P&L: `exit − entry` (long) or `entry − exit` (short) |
| `return_pct` | `float` | `pnl / entry_price × 100` |
| `side` | `"long" \| "short"` | Trade direction |

---

## `BacktestResult` Dataclass

```python
@dataclasses.dataclass(frozen=True)
class BacktestResult:
    # Core
    trade_count:         int        # completed round-trips
    win_rate:            float      # fraction of trades with pnl > 0  (0.0–1.0)
    total_pnl:           float      # sum of all trade pnl values (price units)
    avg_pnl:             float      # total_pnl / trade_count
    trades:              list       # per-trade dicts (see schema above)

    # Return metrics
    strategy_return_pct: float      # compounded % return (see below)
    avg_return_pct:      float      # simple average of per-trade return_pct

    # Benchmark
    spy_return_pct:      float | None   # SPY buy-and-hold % over same date range
    beat_spy:            bool  | None   # strategy_return_pct > spy_return_pct

    # Data window
    data_start_date:     str | None    # first bar date "YYYY-MM-DD"
    data_end_date:       str | None    # last bar date  "YYYY-MM-DD"
    bar_count:           int           # number of bars in df
```

When `trade_count == 0`, all numeric fields are `0.0` / `None` and `trades` is `[]`.
No division-by-zero errors occur.

---

## Compounding Logic (`strategy_return_pct`)

Starting with `initial_capital` (default `$1 000`), the engine reinvests the
full equity into each trade:

```
capital = initial_capital
for each trade:
    shares = capital / entry_price
    capital += pnl * shares          # pnl per unit × shares held
strategy_return_pct = (capital − initial_capital) / initial_capital × 100
```

This assumes full reinvestment of gains/losses into each successive trade.
Fractional shares are allowed.

---

## SPY Benchmark (`spy_return_pct`)

When `spy_df` is provided, the engine computes a buy-and-hold return over
the same date range as `df`:

```
spy_slice = spy_df[(spy_df.index >= df.index[0]) & (spy_df.index <= df.index[-1])]
spy_return_pct = (spy_slice.Close.iloc[-1] / spy_slice.Close.iloc[0] − 1) × 100
beat_spy = strategy_return_pct > spy_return_pct
```

`spy_return_pct` and `beat_spy` are `None` when:
- `spy_df` is `None`
- `spy_df` is empty
- `spy_df` has fewer than 2 bars in the overlapping date range
- An exception occurs during slicing

---

## Serialization

```python
def backtest_to_dict(result: BacktestResult) -> dict:
    return dataclasses.asdict(result)
```

`backtest_to_dict()` converts a `BacktestResult` to a plain dict for JSON
storage (`dcc.Store`) or DB column writes. `dataclasses.asdict()` handles
nested lists (the `trades` list) automatically.

---

## Callers

| Caller | Location | `spy_df` passed? | Display |
|--------|----------|-----------------|---------|
| Technical Chart | `frontend/pages/technical.py` | Yes (fetched alongside ticker) | Full field set |
| Strategy Scanner | `src/scanner/orchestrator.py` | Yes (SPY fetched per scan run) | Full field set in drill-down |

Both callers use `run_backtest()` directly. `compute_performance()` in
`engine.py` is a deprecated thin wrapper for backward compatibility only —
new code should not call it.

---

## Limitations and Caveats

| Limitation | Detail |
|-----------|--------|
| No slippage | Entry and exit at the bar's `Close` price, no spread |
| No commissions | All P&L is gross |
| No position sizing | `strategy_return_pct` uses full reinvestment; `total_pnl` / `avg_pnl` are per-unit |
| Open positions excluded | Trades still open at data end are not closed or counted |
| Price-unit P&L | `total_pnl` is in raw price units, not dollars or percent |
| Single timeframe | No multi-timeframe signal confirmation |
| Data limitations | Driven by yfinance; intraday history is short (7 days for 1-min) |

---

## Extending: Adding a New Metric

1. Add a new field to `BacktestResult` in `frontend/strategy/backtest.py`.
2. Compute the value inside `run_backtest()` and pass it to the constructor.
3. If the metric needs DB storage (Scanner), add a nullable column to
   `src/scanner/models.py` and a migration entry in `src/database.py:init_db()`.
4. Add the new field to `src/api/schemas.py:ScanBacktestItem` if exposed via API.
5. Update both UI pages to display the new field.

No changes to `backtest_to_dict()` are needed — `dataclasses.asdict()`
automatically includes new fields.
