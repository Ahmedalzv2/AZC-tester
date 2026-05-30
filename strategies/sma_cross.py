from __future__ import annotations

from typing import Any

import pandas as pd

from strategies.base import StrategySpec, clamp_position


def build(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    fast = int(params.get("fast", 20))
    slow = int(params.get("slow", 50))
    if fast >= slow:
        raise ValueError("fast must be smaller than slow")
    fast_ma = df["Close"].rolling(fast).mean()
    slow_ma = df["Close"].rolling(slow).mean()
    return clamp_position((fast_ma > slow_ma).fillna(False).astype(float), df.index)


SPEC = StrategySpec(
    name="sma_cross",
    label="SMA Cross",
    params={"fast": 20, "slow": 50},
    builder=build,
)
