from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

import app as app_module

DEMO = str(Path(__file__).resolve().parents[1] / "sample_data" / "demo_ohlcv.parquet")


def test_walkforward_endpoint_returns_both_legs_with_decay() -> None:
    req = app_module.WalkForwardRequest(
        data_provider="local_file",
        symbol="DEMO",
        interval="1d",
        file_path=DEMO,
        strategy="sma_cross",
        strategy_params={"fast": 10, "slow": 30},
        oos_fraction=0.3,
        fee_bps=5,
        iterations=200,
    )
    out = app_module.walkforward_endpoint(req)
    assert "in_sample" in out and "out_sample" in out
    assert "decay" in out
    assert "significance" in out["in_sample"]
    assert "significance" in out["out_sample"]
    assert out["in_sample"]["metrics"]["bars"] + out["out_sample"]["metrics"]["bars"] > 0
