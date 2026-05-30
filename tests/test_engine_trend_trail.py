from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))

from engine import run_backtest
from strategies import list_strategies


def make_frame(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "Open": closes,
            "High": [value + 1 for value in closes],
            "Low": [value - 1 for value in closes],
            "Close": closes,
            "Volume": [1000] * len(closes),
        },
        index=idx,
    )


def test_custom_python_can_hold_short_positions_profitably() -> None:
    df = make_frame([100, 100, 90, 80, 70])
    code = """def build_signals(df, params):
    return [0, -1, -1, -1, 0]
"""

    result = run_backtest(
        df=df,
        strategy_name="custom_python",
        params={},
        custom_code=code,
        initial_cash=10_000,
        fee_bps=0,
        interval="1d",
    )

    assert result.metrics["ending_equity"] > 10_000
    assert result.trades
    assert result.trades[0]["side"] == "short"


def test_current_trend_trail_strategy_is_listed_and_backtestable() -> None:
    assert "trend_trail" in list_strategies()

    closes = [100, 101, 102, 103, 104, 105, 106, 108, 110, 112, 115, 118, 122, 126, 130, 128, 125, 121, 118, 114]
    df = make_frame(closes)
    result = run_backtest(
        df=df,
        strategy_name="trend_trail",
        params={"don": 3, "atrN": 3, "atrMult": 2, "trail": 2, "regimeN": 3, "erMin": 0.0},
        initial_cash=10_000,
        fee_bps=0,
        interval="1d",
    )

    assert result.metrics["trade_count"] >= 1
    assert any(abs(point["position"]) == 1 for point in result.curve)
