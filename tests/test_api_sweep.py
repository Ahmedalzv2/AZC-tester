from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

import app as app_module

DEMO = str(Path(__file__).resolve().parents[1] / "sample_data" / "demo_ohlcv.parquet")


def test_backtest_response_now_carries_significance() -> None:
    req = app_module.BacktestRequest(
        data_provider="local_file",
        symbol="DEMO",
        interval="1d",
        file_path=DEMO,
        strategy="sma_cross",
        strategy_params={"fast": 10, "slow": 30},
        fee_bps=5,
    )
    out = app_module.backtest(req)
    assert "significance" in out
    assert "tstat" in out["significance"]
    assert "pvalue" in out["significance"]


def test_sweep_endpoint_returns_sorted_runs_with_significance() -> None:
    req = app_module.SweepRequest(
        data_provider="local_file",
        symbol="DEMO",
        interval="1d",
        file_path=DEMO,
        strategy="sma_cross",
        grid={"fast": [5, 10], "slow": [20, 30]},
        fee_bps=5,
        iterations=200,
    )
    out = app_module.sweep_endpoint(req)
    assert out["count"] == 4
    assert len(out["runs"]) == 4
    returns = [r["metrics"]["total_return_pct"] for r in out["runs"]]
    assert returns == sorted(returns, reverse=True)
    assert out["best"]["params"] == out["runs"][0]["params"]
    for run in out["runs"]:
        assert "significance" in run and "tstat" in run["significance"]
