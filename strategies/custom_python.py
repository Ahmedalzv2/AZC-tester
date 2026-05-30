from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from strategies.base import StrategySpec, clamp_position


def build(df: pd.DataFrame, params: dict[str, Any], code: str) -> pd.Series:
    if not code.strip():
        raise ValueError("custom strategy requires Python code")

    scope: dict[str, Any] = {}
    safe_globals: dict[str, Any] = {
        "pd": pd,
        "np": np,
    }
    exec(code, safe_globals, scope)
    build_signals = scope.get("build_signals") or safe_globals.get("build_signals")
    if not callable(build_signals):
        raise ValueError("custom code must define build_signals(df, params)")
    raw = build_signals(df.copy(), params)
    if isinstance(raw, pd.DataFrame):
        if "position" not in raw.columns:
            raise ValueError("custom DataFrame output must include a 'position' column")
        raw = raw["position"]
    return clamp_position(raw, df.index)


SPEC = StrategySpec(
    name="custom_python",
    label="Custom Python",
    params={},
    builder=None,
    uses_custom_code=True,
)
