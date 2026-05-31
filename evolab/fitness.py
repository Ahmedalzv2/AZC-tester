"""Fitness: evolve on in-sample, validate champions out-of-sample.

Selection score is the IS mean net-R only — the OOS slice is never optimized
against, it just decides whether a genome qualifies as a champion under a
Bonferroni bar that the caller deflates by the cumulative lifetime trial count.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from bracket_signals import SIGNALS, simulate_signal
from engine_bracket import Bar
from evolab.data import TAKER
from evolab.genome import FIXED_PARAMS, Genome
from stats import _default_lags, bootstrap_pvalue, newey_west_tstat

TREND_FAMILIES = {"donchian_break", "ts_momentum", "ma_cross", "bollinger_break"}
MIN_OOS_TRADES = 40
P_SEED = 0  # fixed -> deterministic bootstrap p-values


@dataclass
class FitnessResult:
    genome: Genome
    is_n: int
    is_score: float
    is_t: float
    oos_n: int
    oos_mean: float
    oos_t: float
    oos_p: float
    is_champion_candidate: bool


def _tstat(arr: np.ndarray) -> float:
    a = np.asarray(arr, dtype=float)
    return float(newey_west_tstat(a, lags=_default_lags(a.size))) if a.size >= 2 else 0.0


def _pvalue(arr: np.ndarray) -> float:
    a = np.asarray(arr, dtype=float)
    return float(bootstrap_pvalue(a, seed=P_SEED)) if a.size >= 2 else 1.0


# Acklam's inverse-normal-CDF approximation (|err| < 1.15e-9), no scipy needed.
_A = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
      1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
_B = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
      6.680131188771972e+01, -1.328068155288572e+01)
_C = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
      -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
_D = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
      3.754408661907416e+00)


def _probit(p: float) -> float:
    """Standard-normal quantile Phi^-1(p) for p in (0, 1)."""
    if p <= 0.02425:
        q = (-2.0 * np.log(p)) ** 0.5
        return (((((_C[0]*q+_C[1])*q+_C[2])*q+_C[3])*q+_C[4])*q+_C[5]) / \
               ((((_D[0]*q+_D[1])*q+_D[2])*q+_D[3])*q+1.0)
    if p < 0.97575:
        q = p - 0.5
        r = q * q
        return (((((_A[0]*r+_A[1])*r+_A[2])*r+_A[3])*r+_A[4])*r+_A[5])*q / \
               (((((_B[0]*r+_B[1])*r+_B[2])*r+_B[3])*r+_B[4])*r+1.0)
    q = (-2.0 * np.log(1.0 - p)) ** 0.5
    return -(((((_C[0]*q+_C[1])*q+_C[2])*q+_C[3])*q+_C[4])*q+_C[5]) / \
            ((((_D[0]*q+_D[1])*q+_D[2])*q+_D[3])*q+1.0)


def _critical_t(alpha_deflated: float) -> float:
    """One-sided Bonferroni t-bar for a deflated alpha. Continuous (no resolution
    floor, unlike a 2000-iter bootstrap p), so an exceptional edge can always
    clear it; floored at 2.0 so the bar never loosens below the original gate.
    With n>=MIN_OOS_TRADES the normal quantile approximates the t critical value."""
    a = min(0.5, max(alpha_deflated, 1e-300))  # clamp: log(0) guard, never loosen past 0.5
    return max(2.0, -_probit(a))


def _passes_gate(is_score, oos_n, oos_mean, oos_t, oos_p, alpha_deflated) -> bool:
    # oos_p is retained for reporting; it is NOT the binding constraint — a 2000-
    # iteration bootstrap floors at ~5e-4, which made `oos_p < alpha_deflated`
    # unsatisfiable once cumulative trials pushed alpha below that floor.
    return bool(
        oos_n >= MIN_OOS_TRADES and oos_mean > 0 and is_score > 0
        and oos_t >= _critical_t(alpha_deflated)
    )


def _net_rs(bars: list[Bar], genome: Genome) -> list[float]:
    fn = SIGNALS[genome.family]
    params = {**genome.params, **FIXED_PARAMS.get(genome.family, {}), **TAKER}
    return [t["netR"] for t in simulate_signal(bars, fn, params)]


def evaluate(genome: Genome, splits: tuple[list[Bar], list[Bar]], alpha_deflated: float) -> FitnessResult:
    is_bars, oos_bars = splits
    try:
        is_rs = np.asarray(_net_rs(is_bars, genome), dtype=float)
        oos_rs = np.asarray(_net_rs(oos_bars, genome), dtype=float)
    except Exception:
        # A broken genome scores as dead, never aborts the generation.
        return FitnessResult(genome, 0, float("-inf"), 0.0, 0, 0.0, 0.0, 1.0, False)

    is_score = float(is_rs.mean()) if is_rs.size else float("-inf")
    oos_mean = float(oos_rs.mean()) if oos_rs.size else 0.0
    oos_t, oos_p = _tstat(oos_rs), _pvalue(oos_rs)
    candidate = _passes_gate(is_score, oos_rs.size, oos_mean, oos_t, oos_p, alpha_deflated)
    return FitnessResult(
        genome=genome, is_n=int(is_rs.size), is_score=is_score, is_t=_tstat(is_rs),
        oos_n=int(oos_rs.size), oos_mean=oos_mean, oos_t=oos_t, oos_p=oos_p,
        is_champion_candidate=candidate,
    )


def assess(family: str, params: dict, is_bars: list[Bar], oos_bars: list[Bar]) -> dict:
    """One-off honest verdict for an externally-submitted strategy (e.g. AZC).

    A single submitted strategy is ONE hypothesis, not a multiple-testing search,
    so there is NO cumulative deflation here — just standard significance on the
    fee-accurate out-of-sample tape. Still only a hypothesis until a live forward
    test confirms it.
    """
    if family not in SIGNALS:
        raise ValueError(f"unknown family '{family}'; known: {sorted(SIGNALS)}")
    g = Genome(family, dict(params))
    is_rs = np.asarray(_net_rs(is_bars, g), dtype=float)
    oos_rs = np.asarray(_net_rs(oos_bars, g), dtype=float)

    is_mean = float(is_rs.mean()) if is_rs.size else 0.0
    oos_mean = float(oos_rs.mean()) if oos_rs.size else 0.0
    is_t = _tstat(is_rs)
    oos_t, oos_p = _tstat(oos_rs), _pvalue(oos_rs)

    holds = bool(oos_rs.size >= MIN_OOS_TRADES and oos_mean > 0 and is_mean > 0
                 and oos_mean >= 0.5 * is_mean)
    real = bool(oos_rs.size >= MIN_OOS_TRADES and oos_mean > 0 and is_mean > 0
                and oos_t >= 2.0 and oos_p < 0.05)
    if real:
        verdict = "real"
    elif oos_rs.size >= MIN_OOS_TRADES and oos_mean > 0 and oos_t >= 1.0:
        verdict = "marginal"
    else:
        verdict = "noise"

    return {
        "verdict": verdict,
        "family": family,
        "net_R_oos": round(oos_mean * oos_rs.size, 4),
        "is": {"n": int(is_rs.size), "meanR": round(is_mean, 4), "t": round(is_t, 2)},
        "oos": {"n": int(oos_rs.size), "meanR": round(oos_mean, 4),
                "t": round(oos_t, 2), "p": round(oos_p, 4), "holds": holds},
        "fees": "all-taker (engine_bracket TAKER model)",
        "deflation": "none (single hypothesis — not a multiple-testing search)",
        "note": "A verdict, not a green light. Still only a hypothesis until a live forward test.",
    }
