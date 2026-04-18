"""
MA Crossover
Generates a BUY signal when the fast moving average crosses above the slow MA,
and a SELL signal when the fast MA crosses below the slow MA.
"""
from __future__ import annotations

import pandas as pd

from frontend.strategy.engine import StrategyContext, StrategyResult

PARAMS = {
    "fast_period": {
        "type": "int",   "default": 10,      "min": 2,   "max": 100,
        "desc": "Fast MA period",
    },
    "slow_period": {
        "type": "int",   "default": 50,      "min": 5,   "max": 200,
        "desc": "Slow MA period",
    },
    "source": {
        "type": "choice", "default": "Close",
        "options": ["Close", "HL2", "HLC3"],
        "desc": "Price source",
    },
    "ma_type": {
        "type": "choice", "default": "SMA",
        "options": ["SMA", "EMA"],
        "desc": "MA type",
    },
}


def strategy(ctx: StrategyContext) -> StrategyResult:
    fast_period = int(ctx.params.get("fast_period", PARAMS["fast_period"]["default"]))
    slow_period = int(ctx.params.get("slow_period", PARAMS["slow_period"]["default"]))
    source      = ctx.params.get("source",  PARAMS["source"]["default"])
    ma_type     = ctx.params.get("ma_type", PARAMS["ma_type"]["default"])

    src     = ctx.get_source(source)
    fast_ma = ctx.compute_ma(src, ma_type, fast_period)
    slow_ma = ctx.compute_ma(src, ma_type, slow_period)

    above      = fast_ma > slow_ma
    above_prev = above.shift(1, fill_value=False)

    signals = pd.Series(0, index=ctx.df.index, dtype=int)
    signals[above  & ~above_prev] = 1    # crossover: fast crosses above slow → BUY
    signals[~above &  above_prev] = -1   # crossunder: fast crosses below slow → SELL

    return StrategyResult(
        signals=signals,
        metadata={"fast_ma": fast_ma, "slow_ma": slow_ma},
    )
