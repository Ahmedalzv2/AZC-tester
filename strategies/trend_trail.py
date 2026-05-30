from __future__ import annotations

from typing import Any

import pandas as pd

from strategies.base import StrategySpec, clamp_position


def efficiency_ratio(df: pd.DataFrame, i: int, lookback: int) -> float:
    if i - lookback < 0:
        return 0.0
    closes = df["Close"]
    net = abs(float(closes.iloc[i]) - float(closes.iloc[i - lookback]))
    volatility = 0.0
    for k in range(i - lookback + 1, i + 1):
        volatility += abs(float(closes.iloc[k]) - float(closes.iloc[k - 1]))
    return net / volatility if volatility > 0 else 0.0


def atr(df: pd.DataFrame, i: int, period: int) -> float:
    total = 0.0
    for k in range(i - period + 1, i + 1):
        high = float(df["High"].iloc[k])
        low = float(df["Low"].iloc[k])
        prev_close = float(df["Close"].iloc[k - 1])
        total += max(high - low, abs(high - prev_close), abs(low - prev_close))
    return total / period


def build(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    don = int(params.get("don", 30))
    atr_n = int(params.get("atrN", 14))
    atr_mult = float(params.get("atrMult", 2))
    trail = float(params.get("trail", 3))
    regime_n = int(params.get("regimeN", 20))
    er_min = float(params.get("erMin", 0.35))

    position = pd.Series(0.0, index=df.index)
    active: dict[str, float] | None = None
    min_ready = max(don, atr_n) + 1

    for i in range(len(df)):
        if i < min_ready:
            continue

        close = float(df["Close"].iloc[i])
        bar_high = float(df["High"].iloc[i])
        bar_low = float(df["Low"].iloc[i])
        atr_value = atr(df, i, atr_n)

        if active is None:
            hh = float(df["High"].iloc[i - don:i].max())
            ll = float(df["Low"].iloc[i - don:i].min())
            direction = 0
            if close > hh:
                direction = 1
            elif close < ll:
                direction = -1

            if direction == 0 or atr_value <= 0:
                continue
            if er_min > 0 and efficiency_ratio(df, i, regime_n) < er_min:
                continue

            initial_stop = close - atr_mult * atr_value if direction > 0 else close + atr_mult * atr_value
            active = {
                "direction": float(direction),
                "entry": close,
                "initial_stop": initial_stop,
                "atr_at_entry": atr_value,
                "hwm": close,
                "lwm": close,
            }
            position.iloc[i] = float(direction)
            continue

        direction = int(active["direction"])
        trail_dist = trail * float(active["atr_at_entry"])
        prior_hwm = float(active["hwm"])
        prior_lwm = float(active["lwm"])

        if direction > 0:
            stop = max(float(active["initial_stop"]), prior_hwm - trail_dist)
            if bar_low <= stop:
                active = None
                position.iloc[i] = 0.0
            else:
                active["hwm"] = max(prior_hwm, bar_high)
                active["lwm"] = min(prior_lwm, bar_low)
                position.iloc[i] = 1.0
        else:
            stop = min(float(active["initial_stop"]), prior_lwm + trail_dist)
            if bar_high >= stop:
                active = None
                position.iloc[i] = 0.0
            else:
                active["hwm"] = max(prior_hwm, bar_high)
                active["lwm"] = min(prior_lwm, bar_low)
                position.iloc[i] = -1.0

    return clamp_position(position, df.index)


SPEC = StrategySpec(
    name="trend_trail",
    label="AZC Trend Trail",
    params={"don": 30, "atrN": 14, "atrMult": 2, "trail": 3, "regimeN": 20, "erMin": 0.35},
    builder=build,
)
