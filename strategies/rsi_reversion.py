from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from strategies.base import StrategySpec, clamp_position


def build(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    period = int(params.get("period", 14))
    lower = float(params.get("lower", 30))
    upper = float(params.get("upper", 55))
    delta = df["Close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    entries = rsi < lower
    exits = rsi > upper
    position = pd.Series(0.0, index=df.index)
    in_position = False
    for idx in df.index:
        if entries.loc[idx]:
            in_position = True
        elif exits.loc[idx]:
            in_position = False
        position.loc[idx] = float(in_position)
    return clamp_position(position, df.index)


SPEC = StrategySpec(
    name="rsi_reversion",
    label="RSI Reversion",
    params={"period": 14, "lower": 30, "upper": 55},
    builder=build,
)
