"""Sanity tests for the vol-targeted trend portfolio (synthetic data, no network)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from portfolio_trend import build_portfolio, current_targets, donchian_trail_position


def _trending_ohlc(n=900, slope=0.05, seed=1):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(slope, 1.0, n))
    close = np.maximum(close, 1.0)
    idx = pd.date_range("2015-01-01", periods=n, freq="B", tz="UTC")
    high = close + rng.uniform(0.1, 1.0, n)
    low = close - rng.uniform(0.1, 1.0, n)
    return pd.DataFrame({"Open": close, "High": high, "Low": low, "Close": close}, index=idx)


def test_position_is_ternary():
    df = _trending_ohlc()
    pos = donchian_trail_position(df["Close"], df["High"], df["Low"], don=50, trail=5)
    assert set(pos.unique()).issubset({-1.0, 0.0, 1.0})
    assert pos.abs().sum() > 0  # an uptrend should produce long exposure


def test_uptrend_makes_money_long():
    up = _trending_ohlc(slope=0.08, seed=2)
    res = build_portfolio({"AAA": up, "BBB": _trending_ohlc(slope=0.06, seed=3)}, vol_target=0.15)
    assert "sharpe" in res.metrics and "max_dd_pct" in res.metrics
    assert res.metrics["cagr_pct"] > 0  # trend-follower long a clean uptrend should profit


def test_vol_targeting_in_ballpark():
    res = build_portfolio({s: _trending_ohlc(seed=i) for i, s in enumerate(["A", "B", "C", "D"])},
                          vol_target=0.15)
    # realized vol should land roughly near target (loose band — synthetic).
    assert 0.05 < res.metrics["vol_pct"] / 100 < 0.40


def test_current_targets_shape():
    t = current_targets({s: _trending_ohlc(seed=i + 9) for i, s in enumerate(["A", "B", "C"])})
    assert isinstance(t, dict)
    for w in t.values():
        assert abs(w) <= 5
