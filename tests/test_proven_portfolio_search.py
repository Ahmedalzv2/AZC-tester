"""Tests for the proven-universe PORTFOLIO-genome search.

Synthetic OHLC only — no network. Verifies the scorer produces honest
OOS + full metrics, that the multiple-testing deflation actually bites
(sr_star grows with the number of trials), and that the search report
locates the prod config and ranks by OOS, not in-sample.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from proven_portfolio_search import score_config, run_search, PROD


def _synth_ohlc(seed: int, n: int = 700) -> pd.DataFrame:
    """A trending-then-reverting daily series so Donchian breakouts fire."""
    rng = np.random.default_rng(seed)
    # alternating drift regimes + noise -> real trends to break out of
    drift = np.concatenate([np.full(n // 3, 0.0015), np.full(n // 3, -0.0012),
                            np.full(n - 2 * (n // 3), 0.0010)])
    ret = drift + rng.normal(0, 0.012, n)
    close = 100 * np.exp(np.cumsum(ret))
    idx = pd.bdate_range("2015-01-01", periods=n)
    high = close * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.004, n)))
    return pd.DataFrame({"Open": close, "High": high, "Low": low, "Close": close}, index=idx)


def _universe(k: int = 4) -> dict[str, pd.DataFrame]:
    return {f"A{i}": _synth_ohlc(seed=i) for i in range(k)}


def test_score_config_returns_oos_and_full_metrics():
    ohlc = _universe()
    r = score_config(ohlc, don=100, trail=5, vol_target=0.15, vol_lookback=60, oos_frac=0.30)
    for k in ("full", "oos"):
        assert "sharpe_ann" in r[k] and "hac_t" in r[k] and "n" in r[k]
        assert np.isfinite(r[k]["sharpe_ann"]) and np.isfinite(r[k]["hac_t"])
    # OOS window is strictly smaller than full
    assert r["oos"]["n"] < r["full"]["n"]
    # per-obs sharpe + moments present for deflation
    assert np.isfinite(r["per_obs_sharpe"]) and np.isfinite(r["skew"]) and np.isfinite(r["kurt"])


def test_run_search_locates_prod_and_deflates():
    ohlc = _universe()
    grid = {"don": [50, 100, 150], "trail": [3, 5], "vol_target": [0.10, 0.15], "vol_lookback": [60]}
    rep = run_search(ohlc, grid, prod=PROD, oos_frac=0.30)
    # every grid cell scored
    assert rep["n_configs"] == 3 * 2 * 2 * 1
    # prod config is located and ranked
    assert rep["prod"]["genome"]["don"] == PROD["don"]
    assert "oos_rank" in rep["prod"] and 1 <= rep["prod"]["oos_rank"] <= rep["n_configs"]
    # deflation actually applied: sr_star > 0 once there is selection across >1 trial
    assert rep["deflated"]["n_trials"] == rep["n_configs"]
    assert rep["deflated"]["sr_star"] > 0.0
    # dsr is a probability
    assert 0.0 <= rep["deflated"]["dsr"] <= 1.0
    # best is chosen by OOS sharpe, and the verdict field exists
    assert rep["best_by_oos"]["oos"]["sharpe_ann"] >= rep["prod"]["oos"]["sharpe_ann"] - 1e-9
    assert rep["verdict"] in ("clears-deflated-bar", "robust-but-not-significant", "prod-near-optimal", "no-improvement")


def test_deflation_tightens_with_more_trials():
    # sr_star (the bar a winner must beat) must grow as more configs are searched
    from overfit import expected_max_sharpe
    var = 0.01
    assert expected_max_sharpe(50, var) > expected_max_sharpe(5, var) > 0.0
