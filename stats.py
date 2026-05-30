"""Significance layer for the backtest lab.

A single equity curve cannot tell you whether an edge is real or noise. These
helpers turn a curve's per-bar returns into the two numbers that can:

- a Newey-West (HAC) t-stat of the mean return, robust to autocorrelation;
- a one-sided bootstrap p-value for "mean return > 0".

This is the lesson burned in by the AZC trend lane: the curve looked great
until the HAC t-stat came back under 1.2 and the edge evaporated. Surface it.
"""
from __future__ import annotations

from typing import Any

import numpy as np


def returns_from_curve(curve: list[dict[str, Any]]) -> np.ndarray:
    """Per-step equity returns derived from a backtest curve."""
    equity = np.asarray([float(point["equity"]) for point in curve], dtype=float)
    if equity.size < 2:
        return np.asarray([], dtype=float)
    prev = equity[:-1]
    # guard against zero/negative equity steps producing inf/nan
    safe_prev = np.where(prev == 0.0, np.nan, prev)
    return (equity[1:] / safe_prev) - 1.0


def _default_lags(n: int) -> int:
    """Newey-West automatic bandwidth: floor(4 * (n/100)^(2/9))."""
    if n < 2:
        return 0
    return int(np.floor(4 * (n / 100.0) ** (2.0 / 9.0)))


def newey_west_tstat(returns: np.ndarray, lags: int | None = None) -> float:
    """HAC t-stat of the mean return. lags=0 reduces to the ordinary t-stat."""
    x = np.asarray(returns, dtype=float)
    x = x[np.isfinite(x)]
    n = x.size
    if n < 2:
        return 0.0
    mean = x.mean()
    demeaned = x - mean
    if lags is None:
        lags = _default_lags(n)
    lags = max(0, min(lags, n - 1))

    gamma0 = np.dot(demeaned, demeaned) / n
    var = gamma0
    for k in range(1, lags + 1):
        weight = 1.0 - k / (lags + 1.0)
        gamma_k = np.dot(demeaned[k:], demeaned[:-k]) / n
        var += 2.0 * weight * gamma_k

    if var <= 0.0:
        return 0.0
    se = np.sqrt(var / n)
    if se == 0.0:
        return 0.0
    return float(mean / se)


def bootstrap_pvalue(
    returns: np.ndarray,
    iterations: int = 2000,
    seed: int = 0,
) -> float:
    """One-sided bootstrap p-value for H1: mean return > 0.

    Centers the sample at zero (the null), resamples with replacement, and
    measures how often a null-world mean reaches the observed mean.
    """
    x = np.asarray(returns, dtype=float)
    x = x[np.isfinite(x)]
    n = x.size
    if n < 2:
        return 1.0
    observed = x.mean()
    if observed <= 0.0:
        # No positive edge to test; report it as non-significant.
        return 1.0
    centered = x - observed
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(iterations, n))
    boot_means = centered[idx].mean(axis=1)
    hits = int(np.count_nonzero(boot_means >= observed))
    # +1 smoothing so a perfect signal reports a small floor, not exactly 0.
    return (hits + 1) / (iterations + 1)


def significance(
    curve: list[dict[str, Any]],
    lags: int | None = None,
    iterations: int = 2000,
    seed: int = 0,
) -> dict[str, Any]:
    """Bundle the significance verdict for a single backtest curve."""
    returns = returns_from_curve(curve)
    n = int(returns.size)
    if n < 2:
        return {
            "n": n,
            "mean_return": 0.0,
            "tstat": 0.0,
            "pvalue": 1.0,
            "lags": 0,
            "significant": False,
        }
    used_lags = _default_lags(n) if lags is None else max(0, min(lags, n - 1))
    tstat = newey_west_tstat(returns, lags=used_lags)
    pvalue = bootstrap_pvalue(returns, iterations=iterations, seed=seed)
    return {
        "n": n,
        "mean_return": float(returns.mean()),
        "tstat": round(tstat, 3),
        "pvalue": round(pvalue, 4),
        "lags": int(used_lags),
        # The bar AZC taught us: |t| >= 2 AND p < 0.05 before you trust it.
        "significant": bool(abs(tstat) >= 2.0 and pvalue < 0.05),
    }
