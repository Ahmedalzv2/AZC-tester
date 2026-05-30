from __future__ import annotations

from typing import Any

import pandas as pd

from strategies.base import StrategySpec, clamp_position


def build(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    lookback = int(params.get("lookback", 20))
    exit_lookback = int(params.get("exit_lookback", 10))
    highs = df["High"].rolling(lookback).max().shift(1)
    lows = df["Low"].rolling(exit_lookback).min().shift(1)
    entries = df["Close"] > highs
    exits = df["Close"] < lows
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
    name="breakout",
    label="Breakout",
    params={"lookback": 20, "exit_lookback": 10},
    builder=build,
)
