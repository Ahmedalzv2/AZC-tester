from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

StrategyBuilder = Callable[[pd.DataFrame, dict[str, Any]], pd.Series]


@dataclass(slots=True)
class StrategySpec:
    name: str
    label: str
    params: dict[str, Any]
    builder: StrategyBuilder | None
    uses_custom_code: bool = False
    # "position" = close-to-close fractional engine (engine.py);
    # "bracket"  = AZC stop/target execution engine (engine_bracket.py).
    execution: str = "position"
    # For bracket strategies: base bars are resampled positionally by this
    # factor before the engine runs (e.g. 16 = 15m -> 4h). 1 = no resample.
    resample_per: int = 1
    long_short: bool = True
    needs_ohlc: bool = True
    needs_volume: bool = False
    tags: list[str] = field(default_factory=list)


def clamp_position(raw: pd.Series, index: pd.Index) -> pd.Series:
    if not isinstance(raw, pd.Series):
        raw = pd.Series(raw, index=index)
    return raw.reindex(index).fillna(0.0).clip(-1, 1).astype(float)
