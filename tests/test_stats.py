from __future__ import annotations

from pathlib import Path
import sys

import numpy as np

sys.path.append(str(Path(__file__).resolve().parents[1]))

from stats import (
    bootstrap_pvalue,
    newey_west_tstat,
    returns_from_curve,
    significance,
)


def test_returns_from_curve_derives_step_returns() -> None:
    curve = [{"equity": 100.0}, {"equity": 110.0}, {"equity": 121.0}]
    out = returns_from_curve(curve)
    assert np.allclose(out, [0.1, 0.1])


def test_newey_west_zero_lag_matches_ordinary_t_stat() -> None:
    rng = np.random.default_rng(7)
    returns = rng.normal(0.001, 0.02, size=400)
    n = len(returns)
    expected = returns.mean() / (returns.std(ddof=0) / np.sqrt(n))
    assert np.isclose(newey_west_tstat(returns, lags=0), expected)


def test_newey_west_flags_real_edge_with_high_t() -> None:
    # Strong, persistent positive drift -> t-stat should be clearly significant.
    rng = np.random.default_rng(1)
    returns = rng.normal(0.004, 0.01, size=500)
    assert newey_west_tstat(returns) > 3.0


def test_newey_west_rejects_noise_with_low_t() -> None:
    # Zero-mean symmetric noise -> not significant.
    rng = np.random.default_rng(2)
    returns = rng.normal(0.0, 0.02, size=500)
    assert abs(newey_west_tstat(returns)) < 2.0


def test_bootstrap_pvalue_low_for_clear_signal() -> None:
    rng = np.random.default_rng(3)
    returns = rng.normal(0.005, 0.01, size=300)
    assert bootstrap_pvalue(returns, iterations=2000, seed=0) < 0.05


def test_bootstrap_pvalue_high_for_zero_mean_noise() -> None:
    rng = np.random.default_rng(4)
    returns = rng.normal(0.0, 0.02, size=300)
    returns = returns - returns.mean()  # genuinely centered: no edge to find
    assert bootstrap_pvalue(returns, iterations=2000, seed=0) > 0.10


def test_significance_bundles_metrics_from_curve() -> None:
    rng = np.random.default_rng(5)
    steps = rng.normal(0.003, 0.01, size=250)
    equity = 10_000 * np.cumprod(1 + steps)
    curve = [{"equity": float(v)} for v in equity]
    out = significance(curve, iterations=1000, seed=0)
    assert out["n"] == len(curve) - 1
    assert "tstat" in out and "pvalue" in out and "mean_return" in out
    assert out["pvalue"] < 0.05
    assert out["tstat"] > 2.0
