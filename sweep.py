"""Parameter sweep layer.

Turns the backtester from a one-curve-at-a-time tool into a grid search: run
every combination of a parameter grid, attach the significance verdict to each,
and return the table sorted best-first. This is the thing that previously got
done by hand through one-off Hermes runs.

A sweep that returns its best config WITHOUT the significance verdict is a trap:
the top of any grid is the luckiest overfit. Every row carries its t-stat and
p-value so the winner can be sanity-checked, not just celebrated.
"""
from __future__ import annotations

from itertools import product
from typing import Any

import pandas as pd

from engine import run_backtest
from stats import significance


def expand_grid(grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """Cartesian product of a parameter grid -> list of param dicts."""
    if not grid:
        return [{}]
    keys = list(grid.keys())
    value_lists = [grid[k] if isinstance(grid[k], (list, tuple)) else [grid[k]] for k in keys]
    return [dict(zip(keys, combo)) for combo in product(*value_lists)]


def run_sweep(
    df: pd.DataFrame,
    strategy_name: str,
    grid: dict[str, list[Any]],
    base_params: dict[str, Any] | None = None,
    initial_cash: float = 10_000,
    fee_bps: float = 10,
    custom_code: str | None = None,
    interval: str = "1d",
    sort_by: str = "total_return_pct",
    iterations: int = 1000,
) -> dict[str, Any]:
    base_params = base_params or {}
    combos = expand_grid(grid)

    runs: list[dict[str, Any]] = []
    for combo in combos:
        params = {**base_params, **combo}
        try:
            result = run_backtest(
                df=df,
                strategy_name=strategy_name,
                params=params,
                initial_cash=initial_cash,
                fee_bps=fee_bps,
                custom_code=custom_code,
                interval=interval,
            )
            sig = significance(result.curve, iterations=iterations)
            runs.append(
                {
                    "params": combo,
                    "metrics": result.metrics,
                    "significance": sig,
                    "error": None,
                }
            )
        except Exception as exc:  # one bad combo shouldn't sink the sweep
            runs.append(
                {
                    "params": combo,
                    "metrics": None,
                    "significance": None,
                    "error": str(exc),
                }
            )

    def sort_key(run: dict[str, Any]) -> float:
        metrics = run.get("metrics")
        if not metrics or sort_by not in metrics:
            return float("-inf")
        try:
            return float(metrics[sort_by])
        except (TypeError, ValueError):
            return float("-inf")

    runs.sort(key=sort_key, reverse=True)

    best = next((r for r in runs if r.get("metrics") is not None), None)
    return {
        "count": len(runs),
        "sort_by": sort_by,
        "best": best,
        "runs": runs,
    }
