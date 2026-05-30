"""Walk-forward / out-of-sample evaluation.

The single strongest defense against overfit: fit/look on an in-sample slice,
then judge on an out-of-sample slice the strategy never "saw". If the edge only
exists in-sample, the OOS leg exposes it — exactly how the AZC trend lane looked
great until the out-of-sample tape erased it.

This is an honest *holdout*, not a parameter optimizer: it runs the SAME params
on both legs and reports the decay (OOS return - IS return). A large negative
decay is the tell that the in-sample result was luck, not edge.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from engine import run_backtest
from stats import significance


def _leg(
    df: pd.DataFrame,
    strategy_name: str,
    params: dict[str, Any],
    initial_cash: float,
    fee_bps: float,
    custom_code: str | None,
    interval: str,
    iterations: int,
) -> dict[str, Any]:
    result = run_backtest(
        df=df,
        strategy_name=strategy_name,
        params=params,
        initial_cash=initial_cash,
        fee_bps=fee_bps,
        custom_code=custom_code,
        interval=interval,
    )
    return {
        "metrics": result.metrics,
        "curve": result.curve,
        "significance": significance(result.curve, iterations=iterations),
    }


def walk_forward(
    df: pd.DataFrame,
    strategy_name: str,
    params: dict[str, Any] | None = None,
    oos_fraction: float = 0.3,
    initial_cash: float = 10_000,
    fee_bps: float = 10,
    custom_code: str | None = None,
    interval: str = "1d",
    iterations: int = 1000,
) -> dict[str, Any]:
    if not 0.05 <= oos_fraction <= 0.95:
        raise ValueError("oos_fraction must be between 0.05 and 0.95")
    params = params or {}
    ordered = df.copy().sort_index()
    n = len(ordered)
    if n < 4:
        raise ValueError("Not enough bars for a walk-forward split")

    split_index = int(n * (1 - oos_fraction))
    split_index = max(1, min(split_index, n - 1))
    in_df = ordered.iloc[:split_index]
    out_df = ordered.iloc[split_index:]

    in_leg = _leg(in_df, strategy_name, params, initial_cash, fee_bps, custom_code, interval, iterations)
    out_leg = _leg(out_df, strategy_name, params, initial_cash, fee_bps, custom_code, interval, iterations)

    decay = round(
        out_leg["metrics"]["total_return_pct"] - in_leg["metrics"]["total_return_pct"], 3
    )
    return {
        "split_index": split_index,
        "oos_fraction": oos_fraction,
        "params": params,
        "in_sample": in_leg,
        "out_sample": out_leg,
        # OOS return minus IS return. Strongly negative = the in-sample edge
        # did not survive out of sample (overfit tell).
        "decay": decay,
        "holds_out_of_sample": bool(
            out_leg["metrics"]["total_return_pct"] > 0
            and out_leg["significance"]["significant"]
        ),
    }
