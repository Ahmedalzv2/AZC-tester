"""Multiple-testing / overfit deflation — making the green light honest.

A parameter sweep runs N configs, sorts best-first, and the winner's raw
t-stat/p-value is a lie: it's the maximum over N draws, so several configs clear
p<0.05 by pure luck. This is the single most common way a backtest "PASS" turns
into a live loss.

The fix is the Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014):
- Probabilistic Sharpe Ratio (PSR): P(true Sharpe > benchmark), correcting for
  sample length and non-normal returns (skew/kurtosis).
- Deflated Sharpe Ratio (DSR): PSR where the benchmark is the *expected maximum*
  Sharpe under the null given how many configs were tried. Survive that and the
  edge is not just selection noise.

Pure-Python/numpy (no scipy): norm_cdf via erf, norm_ppf via Acklam's rational
approximation, so this adds no dependency.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np

_EULER_MASCHERONI = 0.5772156649015329


def norm_cdf(x: float) -> float:
    """Standard normal CDF via the error function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# Acklam's inverse normal CDF — accurate to ~1e-9 over (0, 1).
_A = (-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
      1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00)
_B = (-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
      6.680131188771972e01, -1.328068155288572e01)
_C = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
      -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00)
_D = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
      3.754408661907416e00)
_P_LOW = 0.02425


def norm_ppf(p: float) -> float:
    """Inverse standard normal CDF (quantile function)."""
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    if p < _P_LOW:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / \
               ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0)
    if p <= 1.0 - _P_LOW:
        q = p - 0.5
        r = q * q
        return (((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5]) * q / \
               (((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1.0)
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / \
            ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0)


def sharpe_moments(returns: Sequence[float]) -> dict[str, float]:
    """Per-observation Sharpe + sample moments of a return series.

    Returns non-excess kurtosis (normal == 3), the convention the PSR formula
    expects."""
    x = np.asarray(returns, dtype=float)
    x = x[np.isfinite(x)]
    n = int(x.size)
    if n < 2:
        return {"sharpe": 0.0, "n": n, "skew": 0.0, "kurt": 3.0}
    mean = float(x.mean())
    sd = float(x.std(ddof=0))
    if sd <= 0.0:
        return {"sharpe": 0.0, "n": n, "skew": 0.0, "kurt": 3.0}
    d = x - mean
    skew = float((d ** 3).mean() / sd ** 3)
    kurt = float((d ** 4).mean() / sd ** 4)
    return {"sharpe": mean / sd, "n": n, "skew": skew, "kurt": kurt}


def probabilistic_sharpe_ratio(
    sharpe: float, n: int, skew: float = 0.0, kurt: float = 3.0, sr_star: float = 0.0
) -> float:
    """P(true per-obs Sharpe > sr_star), adjusting for n, skew, kurtosis."""
    if n < 2:
        return 0.0
    denom = 1.0 - skew * sharpe + ((kurt - 1.0) / 4.0) * sharpe ** 2
    if denom <= 0.0:
        denom = 1e-12
    z = (sharpe - sr_star) * math.sqrt(n - 1) / math.sqrt(denom)
    return norm_cdf(z)


def expected_max_sharpe(n_trials: int, trials_var: float) -> float:
    """Expected maximum Sharpe under the null across n_trials independent trials.

    This is the benchmark a swept winner must beat to not be pure selection
    noise. With a single trial there is no selection, so it is 0."""
    if n_trials <= 1 or trials_var <= 0.0:
        return 0.0
    sd = math.sqrt(trials_var)
    g = _EULER_MASCHERONI
    return sd * (
        (1.0 - g) * norm_ppf(1.0 - 1.0 / n_trials)
        + g * norm_ppf(1.0 - 1.0 / (n_trials * math.e))
    )


def deflated_sharpe_ratio(
    sharpe: float,
    n: int,
    skew: float,
    kurt: float,
    trials_sharpes: Sequence[float],
) -> dict[str, Any]:
    """Deflate a winner's Sharpe by the number of configs it was selected from."""
    arr = np.asarray(trials_sharpes, dtype=float)
    arr = arr[np.isfinite(arr)]
    n_trials = int(arr.size)
    trials_var = float(arr.var(ddof=1)) if n_trials > 1 else 0.0
    sr_star = expected_max_sharpe(n_trials, trials_var)
    return {
        "dsr": probabilistic_sharpe_ratio(sharpe, n, skew, kurt, sr_star),
        "psr_vs_zero": probabilistic_sharpe_ratio(sharpe, n, skew, kurt, 0.0),
        "sr_star": sr_star,
        "n_trials": n_trials,
        "trials_var": trials_var,
    }
