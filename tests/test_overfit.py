"""Tests for the multiple-testing / overfit deflation layer.

The dashboard's worst lie is selection bias: a sweep tries N configs, sorts
best-first, and shows the winner's raw p-value as if it were the only test run.
The Deflated Sharpe Ratio (Bailey & Lopez de Prado) corrects for how many
configs were tried and for non-normal returns. These tests pin its properties.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from overfit import (
    deflated_sharpe_ratio,
    expected_max_sharpe,
    norm_cdf,
    norm_ppf,
    probabilistic_sharpe_ratio,
    sharpe_moments,
)


def test_norm_ppf_inverts_norm_cdf():
    for x in (-2.3, -0.7, 0.0, 0.5, 1.96):
        assert norm_ppf(norm_cdf(x)) == pytest.approx(x, abs=1e-4)


def test_norm_cdf_known_values():
    assert norm_cdf(0.0) == pytest.approx(0.5, abs=1e-6)
    assert norm_cdf(1.96) == pytest.approx(0.975, abs=1e-3)


def test_sharpe_moments_basic():
    r = np.array([0.01, -0.02, 0.03, 0.00, 0.015])
    m = sharpe_moments(r)
    assert m["n"] == 5
    assert m["sharpe"] == pytest.approx(r.mean() / r.std(ddof=0), rel=1e-9)
    # symmetric-ish small sample: just assert kurt is reported as non-excess (~3 baseline)
    assert m["kurt"] > 0


def test_psr_in_unit_interval():
    for sr in (-0.5, 0.0, 0.1, 0.5):
        p = probabilistic_sharpe_ratio(sr, n=100, skew=0.0, kurt=3.0, sr_star=0.0)
        assert 0.0 <= p <= 1.0


def test_psr_increases_with_sharpe():
    lo = probabilistic_sharpe_ratio(0.05, n=200, skew=0.0, kurt=3.0)
    hi = probabilistic_sharpe_ratio(0.20, n=200, skew=0.0, kurt=3.0)
    assert hi > lo


def test_psr_strong_edge_near_one():
    # per-observation Sharpe 0.2 over 500 obs vs a 0 benchmark is overwhelming
    p = probabilistic_sharpe_ratio(0.2, n=500, skew=0.0, kurt=3.0, sr_star=0.0)
    assert p > 0.99


def test_expected_max_sharpe_grows_with_trials():
    var = 0.01
    assert expected_max_sharpe(2, var) < expected_max_sharpe(10, var) < expected_max_sharpe(100, var)


def test_expected_max_sharpe_one_trial_is_zero():
    # No selection happened with a single trial -> no benchmark inflation.
    assert expected_max_sharpe(1, 0.04) == 0.0


def test_dsr_below_psr_when_many_noisy_trials():
    # Same winner, but deflated for having been picked from many noisy trials.
    trials = [0.02, -0.05, 0.08, -0.01, 0.04, -0.03, 0.06, 0.00, 0.03, -0.02]
    best = 0.08
    psr0 = probabilistic_sharpe_ratio(best, n=60, skew=0.0, kurt=3.0, sr_star=0.0)
    out = deflated_sharpe_ratio(best, n=60, skew=0.0, kurt=3.0, trials_sharpes=trials)
    assert out["sr_star"] > 0.0
    assert out["dsr"] < psr0


def test_dsr_strong_single_config_passes():
    # One config, strong edge -> survives (high DSR).
    out = deflated_sharpe_ratio(0.25, n=400, skew=0.0, kurt=3.0, trials_sharpes=[0.25])
    assert out["dsr"] > 0.95


def test_dsr_marginal_winner_many_trials_fails():
    # Marginal best Sharpe selected from 40 noisy trials should NOT survive.
    rng = np.random.default_rng(0)
    trials = list(rng.normal(0.0, 0.05, size=40))
    best = max(trials)
    out = deflated_sharpe_ratio(best, n=60, skew=0.0, kurt=3.0, trials_sharpes=trials)
    assert out["dsr"] < 0.95
