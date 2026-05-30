from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))

from sweep import expand_grid, run_sweep


def make_frame(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "Open": closes,
            "High": [v + 1 for v in closes],
            "Low": [v - 1 for v in closes],
            "Close": closes,
            "Volume": [1000] * len(closes),
        },
        index=idx,
    )


def test_expand_grid_is_cartesian_product() -> None:
    combos = expand_grid({"fast": [5, 10], "slow": [20, 30]})
    assert len(combos) == 4
    assert {"fast": 5, "slow": 20} in combos
    assert {"fast": 10, "slow": 30} in combos


def test_expand_grid_empty_returns_single_empty_combo() -> None:
    assert expand_grid({}) == [{}]


def test_run_sweep_evaluates_every_combo_with_significance() -> None:
    closes = [100, 101, 102, 103, 104, 105, 106, 108, 110, 112,
              115, 118, 122, 126, 130, 128, 125, 121, 118, 114,
              116, 119, 123, 128, 133, 130, 127, 124, 120, 117]
    df = make_frame(closes)

    out = run_sweep(
        df=df,
        strategy_name="sma_cross",
        grid={"fast": [3, 5], "slow": [8, 12]},
        base_params={},
        initial_cash=10_000,
        fee_bps=0,
        interval="1d",
        iterations=200,
    )

    assert out["count"] == 4
    assert len(out["runs"]) == 4
    for run in out["runs"]:
        assert "params" in run and "metrics" in run and "significance" in run
        assert "total_return_pct" in run["metrics"]
        assert "tstat" in run["significance"]


def test_run_sweep_sorts_best_first_by_total_return() -> None:
    closes = [100, 102, 101, 104, 103, 106, 105, 108, 107, 110,
              109, 112, 111, 114, 113, 116, 115, 118, 117, 120]
    df = make_frame(closes)

    out = run_sweep(
        df=df,
        strategy_name="sma_cross",
        grid={"fast": [2, 4], "slow": [6, 10]},
        base_params={},
        initial_cash=10_000,
        fee_bps=0,
        interval="1d",
        sort_by="total_return_pct",
        iterations=200,
    )

    returns = [r["metrics"]["total_return_pct"] for r in out["runs"]]
    assert returns == sorted(returns, reverse=True)
    assert out["best"]["params"] == out["runs"][0]["params"]
