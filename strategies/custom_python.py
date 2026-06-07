from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from strategies.base import StrategySpec, clamp_position


# Curated builtins for the custom-strategy sandbox. Bare `exec(code, {"pd":..})`
# auto-injects the REAL builtins, so `__import__('os').system(...)` runs — an
# unauthenticated RCE on a publicly-routed app. Whitelisting kills the trivial
# import/eval/open escape. NOTE: pd/np themselves still expose file I/O
# (pd.read_csv, df.to_csv), so this is defense-in-depth only — the exec feature
# must also be auth-gated and the host bind-mount narrowed. See review notes.
_ALLOWED_BUILTINS = (
    "abs", "min", "max", "len", "range", "round", "int", "float", "bool",
    "str", "list", "dict", "tuple", "set", "sum", "enumerate", "zip",
    "sorted", "reversed", "map", "filter", "any", "all", "isinstance",
    "ValueError", "TypeError", "KeyError",
)
import builtins as _builtins
_SAFE_BUILTINS = {n: getattr(_builtins, n) for n in _ALLOWED_BUILTINS if hasattr(_builtins, n)}


def build(df: pd.DataFrame, params: dict[str, Any], code: str) -> pd.Series:
    if not code.strip():
        raise ValueError("custom strategy requires Python code")

    scope: dict[str, Any] = {}
    safe_globals: dict[str, Any] = {
        "__builtins__": _SAFE_BUILTINS,
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
