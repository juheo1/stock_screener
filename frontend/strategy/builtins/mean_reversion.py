"""
Mean Reversion (Z-Score)
Enters long when the price drops more than z_entry standard deviations below
the moving average, exits when price reverts to z_exit sigmas.
Enters short symmetrically above the MA.
"""
from __future__ import annotations

import pandas as pd

from frontend.strategy.engine import StrategyContext, StrategyResult

PARAMS = {
    "lookback": {
        "type": "int",   "default": 20,      "min": 5,    "max": 200,
        "desc": "Rolling window for MA and std dev",
    },
    "z_entry": {
        "type": "float", "default": 2.0,      "min": 0.5,  "max": 4.0,
        "desc": "Z-score threshold to enter a position",
    },
    "z_exit": {
        "type": "float", "default": 0.0,      "min": -1.0, "max": 2.0,
        "desc": "Z-score threshold to exit (0 = revert to mean)",
    },
    "source": {
        "type": "choice", "default": "Close",
        "options": ["Close", "HL2", "HLC3"],
        "desc": "Price source",
    },
    "ma_type": {
        "type": "choice", "default": "SMA",
        "options": ["SMA", "EMA"],
        "desc": "Moving average type",
    },
}


def strategy(ctx: StrategyContext) -> StrategyResult:
    lookback = int(ctx.params.get("lookback", PARAMS["lookback"]["default"]))
    z_entry  = float(ctx.params.get("z_entry",  PARAMS["z_entry"]["default"]))
    z_exit   = float(ctx.params.get("z_exit",   PARAMS["z_exit"]["default"]))
    source   = ctx.params.get("source",  PARAMS["source"]["default"])
    ma_type  = ctx.params.get("ma_type", PARAMS["ma_type"]["default"])

    src = ctx.get_source(source)
    ma  = ctx.compute_ma(src, ma_type, lookback)
    std = src.rolling(lookback, min_periods=2).std()
    z   = (src - ma) / std.replace(0.0, float("nan"))

    signals  = pd.Series(0, index=ctx.df.index, dtype=int)
    position = 0  # 0 = flat, 1 = long, -1 = short

    for i in range(len(ctx.df)):
        zi = z.iloc[i]
        if pd.isna(zi):
            continue

        if position == 0:
            if zi <= -z_entry:
                signals.iloc[i] = 1    # enter long
                position = 1
            elif zi >= z_entry:
                signals.iloc[i] = -1   # enter short
                position = -1

        elif position == 1:            # long: exit when price reverts upward
            if zi >= z_exit:
                signals.iloc[i] = -1   # exit long (SELL)
                position = 0

        elif position == -1:           # short: exit when price reverts downward
            if zi <= -z_exit:
                signals.iloc[i] = 1    # exit short (BUY)
                position = 0

    return StrategyResult(signals=signals, metadata={"z_score": z, "ma": ma})
