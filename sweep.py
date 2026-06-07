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
from overfit import deflated_sharpe_ratio, sharpe_moments
from stats import returns_from_curve, significance
from strategies import STRATEGIES


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

    # Bracket bars depend only on the data, not the grid params, so build the
    # 4h-aggregated series ONCE and reuse it for every combo. Previously every
    # combo re-ran to_bars + resample on identical data (N transforms for an
    # N-combo grid) — the dominant cost of a sweep.
    prepared_bars = None
    spec = STRATEGIES.get(strategy_name)
    if spec is not None and getattr(spec, "execution", "position") == "bracket":
        from engine_bracket import prepare_bracket_bars

        prepared_bars = prepare_bracket_bars(df.copy().sort_index())

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
                prepared_bars=prepared_bars,
            )
            sig = significance(result.curve, iterations=iterations)
            # Per-trial Sharpe + moments for the Deflated Sharpe Ratio. Bracket
            # strategies expose per-trade-netR moments in their own significance
            # block (the honest basis); the position engine derives them from the
            # equity-curve returns.
            bsig = result.metrics.get("significance")
            if bsig and bsig.get("basis") == "per-trade netR":
                moments = {"sharpe": bsig.get("sharpe", 0.0), "n": bsig.get("n", 0),
                           "skew": bsig.get("skew", 0.0), "kurt": bsig.get("kurt", 3.0)}
            else:
                moments = sharpe_moments(returns_from_curve(result.curve))
            runs.append(
                {
                    "params": combo,
                    "metrics": result.metrics,
                    "significance": sig,
                    "error": None,
                    "_moments": moments,
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

    # Deflate the winner's Sharpe by how many configs were tried. The top of any
    # grid is the luckiest draw; the DSR asks whether it survives that selection.
    overfit_block = _overfit_verdict(runs, best)

    # _moments is an internal scratch field — strip before returning.
    for r in runs:
        r.pop("_moments", None)

    return {
        "count": len(runs),
        "sort_by": sort_by,
        "best": best,
        "overfit": overfit_block,
        "runs": runs,
    }


def _overfit_verdict(runs: list[dict[str, Any]], best: dict[str, Any] | None) -> dict[str, Any] | None:
    """Deflated Sharpe Ratio verdict for the swept winner vs the whole field."""
    valid = [r for r in runs if r.get("_moments") is not None]
    if not valid or best is None or best.get("_moments") is None:
        return None
    trials_sharpes = [r["_moments"]["sharpe"] for r in valid]
    bm = best["_moments"]
    dsr = deflated_sharpe_ratio(bm["sharpe"], int(bm["n"]), bm["skew"], bm["kurt"], trials_sharpes)
    survives = bool(dsr["dsr"] >= 0.95)
    return {
        "n_configs": len(valid),
        "best_sharpe": round(float(bm["sharpe"]), 6),
        "dsr": round(dsr["dsr"], 4),
        "psr_vs_zero": round(dsr["psr_vs_zero"], 4),
        "sr_star": round(dsr["sr_star"], 6),
        "survives_multiple_testing": survives,
        "verdict": "survives multiple testing" if survives
        else "likely overfit — winner is selection noise",
    }
