from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))

from walkforward import walk_forward


def make_frame(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=len(closes), freq="D", tz="UTC")
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


def _ramp(n: int) -> list[float]:
    # gently rising series so a trend strategy has something to hold
    return [100 + i * 0.5 + (3 if i % 7 == 0 else 0) for i in range(n)]


def test_walk_forward_splits_in_and_out_of_sample() -> None:
    df = make_frame(_ramp(200))
    out = walk_forward(
        df=df,
        strategy_name="sma_cross",
        params={"fast": 5, "slow": 20},
        oos_fraction=0.3,
        interval="1d",
        fee_bps=0,
    )
    # in-sample bars + out-of-sample bars should reconstruct the whole series
    assert out["in_sample"]["metrics"]["bars"] + out["out_sample"]["metrics"]["bars"] == len(df)
    # OOS must start where IS ends (no overlap, no gap)
    assert out["split_index"] == int(len(df) * (1 - 0.3))


def test_walk_forward_carries_significance_on_each_leg() -> None:
    df = make_frame(_ramp(200))
    out = walk_forward(
        df=df,
        strategy_name="sma_cross",
        params={"fast": 5, "slow": 20},
        oos_fraction=0.3,
        interval="1d",
        fee_bps=0,
    )
    for leg in ("in_sample", "out_sample"):
        assert "significance" in out[leg]
        assert "tstat" in out[leg]["significance"]
        assert "total_return_pct" in out[leg]["metrics"]


def test_walk_forward_reports_decay_between_legs() -> None:
    df = make_frame(_ramp(200))
    out = walk_forward(
        df=df,
        strategy_name="sma_cross",
        params={"fast": 5, "slow": 20},
        oos_fraction=0.3,
        interval="1d",
        fee_bps=0,
    )
    is_ret = out["in_sample"]["metrics"]["total_return_pct"]
    oos_ret = out["out_sample"]["metrics"]["total_return_pct"]
    assert out["decay"] == round(oos_ret - is_ret, 3)
