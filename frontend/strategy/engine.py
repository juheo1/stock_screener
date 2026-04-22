"""
frontend.strategy.engine
========================
Core engine for Python-based buy/sell strategies on the Technical Chart.

Responsibilities:
- StrategyContext  : immutable input bundle passed to every strategy function
- StrategyResult   : output contract (signals Series + optional metadata)
- run_strategy()   : constructs context, calls strategy, validates output
- compute_performance() : derives trade-level P&L from signals
- File I/O helpers : list / load / save / delete strategy files
"""
from __future__ import annotations

import datetime
import importlib.util
import json
import re
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd

# ---------------------------------------------------------------------------
# Directory layout
# ---------------------------------------------------------------------------

_STRATEGY_DIR = Path(__file__).resolve().parents[3] / "data" / "strategies"
_STRATEGY_DIR.mkdir(parents=True, exist_ok=True)

_BUILTIN_DIR = Path(__file__).resolve().parent / "builtins"


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

class StrategyError(Exception):
    """Raised when a strategy violates the contract or fails to load/execute."""


@dataclass
class StrategyContext:
    """
    Immutable input bundle passed to each strategy function.

    Helper methods delegate to the corresponding functions in technical.py,
    which are injected at construction time to avoid circular imports.
    """
    df: pd.DataFrame
    ticker: str
    interval: str
    params: dict
    _get_source_fn:       Callable = field(repr=False)
    _compute_ma_fn:       Callable = field(repr=False)
    _compute_indicator_fn: Callable = field(repr=False)

    def get_source(self, name: str) -> pd.Series:
        """Extract a price series by name (Close, Open, High, Low, HL2, HLC3, OHLC4)."""
        return self._get_source_fn(self.df, name)

    def compute_ma(self, src: pd.Series, ma_type: str, length: int) -> pd.Series:
        """Compute a moving average (SMA, EMA, WMA, SMMA/RMA)."""
        return self._compute_ma_fn(src, ma_type, length)

    def compute_indicator(self, spec: dict) -> dict:
        """Compute a full indicator (SMA, EMA, BB, DC, VOLMA) from a spec dict."""
        return self._compute_indicator_fn(self.df, spec)


@dataclass
class StrategyResult:
    """
    Output contract for every strategy function.

    signals : pd.Series[int], index aligned to ctx.df.index
        1  = BUY  (enter long / close short)
       -1  = SELL (enter short / close long)
        0  = HOLD
    metadata : optional dict for extra series (e.g. z_score, ma line)
    """
    signals:  pd.Series
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_result(result: StrategyResult, df: pd.DataFrame) -> None:
    if not isinstance(result, StrategyResult):
        raise StrategyError("Strategy must return a StrategyResult object.")
    if len(result.signals) != len(df):
        raise StrategyError(
            f"signals length ({len(result.signals)}) does not match "
            f"DataFrame length ({len(df)})."
        )
    valid = {-1, 0, 1}
    unique = set(result.signals.dropna().unique())
    bad = unique - valid
    if bad:
        raise StrategyError(
            f"signals contains invalid values: {bad}. Allowed: {{-1, 0, 1}}."
        )


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def _slugify(name: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", name.lower())
    slug = re.sub(r"[\s_-]+", "_", slug).strip("_")
    return slug or "strategy"


def _load_meta(py_path: Path) -> dict:
    json_path = py_path.with_suffix(".json")
    if json_path.is_file():
        try:
            return json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


# ---------------------------------------------------------------------------
# Public API – discovery & lifecycle
# ---------------------------------------------------------------------------

def list_strategies() -> list[dict]:
    """
    Return all available strategies as a list of dicts:
        {"name", "display_name", "is_builtin", "path"}

    Built-in strategies (from frontend/strategy/builtins/) come first,
    then user strategies (from data/strategies/), both sorted by display name.
    """
    strategies: list[dict] = []

    for path in sorted(_BUILTIN_DIR.glob("*.py")):
        if path.stem == "__init__":
            continue
        meta = _load_meta(path)
        strategies.append({
            "name":         path.stem,
            "display_name": meta.get("display_name", path.stem.replace("_", " ").title()),
            "is_builtin":   True,
            "path":         str(path),
        })

    for path in sorted(_STRATEGY_DIR.glob("*.py")):
        meta = _load_meta(path)
        strategies.append({
            "name":         path.stem,
            "display_name": meta.get("display_name", path.stem.replace("_", " ").title()),
            "is_builtin":   False,
            "path":         str(path),
        })

    return sorted(strategies, key=lambda s: (not s["is_builtin"], s["display_name"]))


def load_strategy(name: str, is_builtin: bool = False) -> types.ModuleType:
    """
    Dynamically import a strategy .py file by slug name.
    Raises StrategyError on import failure or missing file.
    """
    base_dir = _BUILTIN_DIR if is_builtin else _STRATEGY_DIR
    path = base_dir / f"{name}.py"

    if not path.is_file():
        raise StrategyError(
            f"Strategy file not found: {path}\n"
            "Check that the strategy name is correct and the file exists."
        )

    spec = importlib.util.spec_from_file_location(f"_strat_{name}", path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise StrategyError(
            f"Failed to load strategy '{name}': {exc}"
        ) from exc

    if not hasattr(module, "strategy") or not callable(module.strategy):
        raise StrategyError(
            f"Strategy '{name}' must define a callable named 'strategy'."
        )

    return module


def run_strategy(
    df: pd.DataFrame,
    ticker: str,
    interval: str,
    strategy_module: types.ModuleType,
    params: dict,
    get_source_fn: Callable,
    compute_ma_fn: Callable,
    compute_indicator_fn: Callable,
) -> StrategyResult:
    """
    Execute a strategy against the given OHLCV DataFrame.

    Constructs a StrategyContext, calls strategy_module.strategy(ctx),
    validates the result, and returns a StrategyResult.
    Wraps non-StrategyError exceptions into StrategyError.
    """
    ctx = StrategyContext(
        df=df,
        ticker=ticker,
        interval=interval,
        params=params,
        _get_source_fn=get_source_fn,
        _compute_ma_fn=compute_ma_fn,
        _compute_indicator_fn=compute_indicator_fn,
    )
    try:
        result = strategy_module.strategy(ctx)
    except StrategyError:
        raise
    except Exception as exc:
        raise StrategyError(f"Strategy execution error: {exc}") from exc

    _validate_result(result, df)
    return result


# ---------------------------------------------------------------------------
# Performance computation
# ---------------------------------------------------------------------------

def compute_performance(
    df: pd.DataFrame,
    signals: pd.Series,
    spy_df: pd.DataFrame | None = None,
) -> dict:
    """
    Deprecated thin wrapper — use ``frontend.strategy.backtest.run_backtest`` directly.

    Calls ``run_backtest()`` and returns a plain dict for backward compatibility.
    """
    from frontend.strategy.backtest import backtest_to_dict, run_backtest
    result = run_backtest(df, signals, spy_df=spy_df)
    return backtest_to_dict(result)


# ---------------------------------------------------------------------------
# Strategy file management
# ---------------------------------------------------------------------------

_TEMPLATE_PY = """\
\"\"\"
{display_name}
\"\"\"
from __future__ import annotations

import pandas as pd
from frontend.strategy.engine import StrategyContext, StrategyResult

PARAMS = {{
    "lookback": {{"type": "int", "default": 20, "min": 5, "max": 200,
                 "desc": "Lookback period"}},
}}


def strategy(ctx: StrategyContext) -> StrategyResult:
    lookback = int(ctx.params.get("lookback", PARAMS["lookback"]["default"]))
    src      = ctx.get_source("Close")
    signals  = pd.Series(0, index=ctx.df.index, dtype=int)
    # TODO: implement strategy logic
    return StrategyResult(signals=signals)
"""


def new_strategy_template(display_name: str) -> tuple[str, str]:
    """Return (py_content, json_content) strings for a blank strategy template."""
    slug = _slugify(display_name)
    now  = datetime.datetime.now().isoformat(timespec="seconds")
    py_content   = _TEMPLATE_PY.format(display_name=display_name)
    json_content = json.dumps({
        "version":        1,
        "name":           slug,
        "display_name":   display_name,
        "description":    "",
        "created":        now,
        "modified":       now,
        "default_params": {"lookback": 20},
    }, indent=2)
    return py_content, json_content


def save_user_strategy(
    display_name: str,
    py_content:   str | None = None,
    params_override: dict | None = None,
) -> str:
    """
    Write a strategy .py and .json sidecar to data/strategies/.
    Returns the slug name of the saved strategy.
    """
    slug = _slugify(display_name)
    now  = datetime.datetime.now().isoformat(timespec="seconds")

    if py_content is None:
        py_content, json_content = new_strategy_template(display_name)
    else:
        json_content = json.dumps({
            "version":        1,
            "name":           slug,
            "display_name":   display_name,
            "description":    "",
            "created":        now,
            "modified":       now,
            "default_params": params_override or {},
        }, indent=2)

    (_STRATEGY_DIR / f"{slug}.py").write_text(py_content,   encoding="utf-8")
    (_STRATEGY_DIR / f"{slug}.json").write_text(json_content, encoding="utf-8")
    return slug


def get_chart_bundle(strategy_module: types.ModuleType) -> dict | None:
    """Return the CHART_BUNDLE dict from a strategy module, or None if absent."""
    return getattr(strategy_module, "CHART_BUNDLE", None)


def delete_user_strategy(name: str) -> bool:
    """
    Delete a user strategy .py and .json from data/strategies/.
    Returns True if the .py file was found and deleted.
    """
    py_path   = _STRATEGY_DIR / f"{name}.py"
    json_path = _STRATEGY_DIR / f"{name}.json"
    deleted   = False
    if py_path.is_file():
        py_path.unlink()
        deleted = True
    if json_path.is_file():
        json_path.unlink()
    return deleted
