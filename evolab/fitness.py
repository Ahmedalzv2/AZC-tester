"""Fitness: evolve on in-sample, validate champions out-of-sample.

Selection score is a *cross-fold robustness* statistic on the in-sample slice:
the IS mean net-R penalized for temporal inconsistency across N_FOLDS
chronological trade-blocks. This is the honest reading of "optimize for OOS
persistence": it rewards edges that hold across IS sub-windows (predictive of
out-of-sample survival) over edges concentrated in one lucky streak (which die
OOS) — without ever optimizing against the OOS slice itself. The OOS slice stays
a clean holdout; it only decides whether a genome qualifies as a champion, under
a Bonferroni bar the caller deflates by the cumulative lifetime trial count.

Why not literally maximize the OOS HAC t (the playbook's shorthand)? Selecting on
the holdout *is* optimizing against it — it converts the only independent
validator into another training slice and re-introduces the overfit it was meant
to catch. Cross-fold robustness gets the same intent (persistence, not in-sample
fit) while keeping the holdout independent.
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

# Cross-fold robustness: split the IS trades into N_FOLDS chronological blocks
# and penalize dispersion of per-fold mean netR. STABILITY_LAMBDA scales the
# penalty (units of netR per unit of cross-fold std). A fold needs at least
# MIN_FOLD_TRADES trades to count toward the stability estimate.
N_FOLDS = 4
MIN_FOLD_TRADES = 5
STABILITY_LAMBDA = 0.5


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
    # Raw IS mean netR (the gate's economic-positivity check) and the cross-fold
    # dispersion that the selection score (is_score) was penalized by. Appended
    # with defaults so the positional dead-genome constructor stays valid.
    is_mean: float = 0.0
    is_dispersion: float = 0.0


def _fold_means(net_rs: np.ndarray, n_folds: int = N_FOLDS) -> list[float]:
    """Mean netR within each chronological trade-block that has enough trades.

    Trades come out of simulate_signal in time order, so contiguous chunks are
    contiguous in time. Blocks thinner than MIN_FOLD_TRADES are dropped (their
    mean is too noisy to inform stability)."""
    if net_rs.size == 0:
        return []
    return [float(b.mean()) for b in np.array_split(net_rs, n_folds) if b.size >= MIN_FOLD_TRADES]


def _stability_score(net_rs: np.ndarray) -> float:
    """Selection fitness: IS mean netR minus a penalty for cross-fold dispersion.

    A persistent edge has similar per-fold means (low dispersion -> small
    penalty); an edge that came from one lucky window has high dispersion and is
    docked. Falls back to the plain mean when fewer than 2 folds clear
    MIN_FOLD_TRADES (too little coverage to judge stability). Empty -> -inf."""
    if net_rs.size == 0:
        return float("-inf")
    mean = float(net_rs.mean())
    fmeans = _fold_means(net_rs)
    if len(fmeans) < 2:
        return mean
    return mean - STABILITY_LAMBDA * float(np.std(fmeans))


def _stability_dispersion(net_rs: np.ndarray) -> float:
    """Cross-fold std of per-fold mean netR (0.0 when stability isn't assessable)."""
    fmeans = _fold_means(net_rs)
    return float(np.std(fmeans)) if len(fmeans) >= 2 else 0.0


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


def _passes_gate(is_mean, oos_n, oos_mean, oos_t, oos_p, alpha_deflated) -> bool:
    # First arg is the RAW IS mean netR (economic positivity), not the
    # stability-penalized selection score — the gate must not reject a genome for
    # in-sample dispersion, only require a real positive IS edge plus an
    # independent OOS hold. oos_p is retained for reporting; it is NOT the binding
    # constraint — a 2000-iteration bootstrap floors at ~5e-4, which made
    # `oos_p < alpha_deflated` unsatisfiable once cumulative trials pushed alpha
    # below that floor.
    return bool(
        oos_n >= MIN_OOS_TRADES and oos_mean > 0 and is_mean > 0
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

    is_mean = float(is_rs.mean()) if is_rs.size else float("-inf")
    is_score = _stability_score(is_rs)  # selection drives off robustness, not raw fit
    is_dispersion = _stability_dispersion(is_rs)
    oos_mean = float(oos_rs.mean()) if oos_rs.size else 0.0
    oos_t, oos_p = _tstat(oos_rs), _pvalue(oos_rs)
    # Gate on the raw IS mean (economic positivity), not the penalized score.
    candidate = _passes_gate(is_mean, oos_rs.size, oos_mean, oos_t, oos_p, alpha_deflated)
    return FitnessResult(
        genome=genome, is_n=int(is_rs.size), is_score=is_score, is_t=_tstat(is_rs),
        oos_n=int(oos_rs.size), oos_mean=oos_mean, oos_t=oos_t, oos_p=oos_p,
        is_champion_candidate=candidate, is_mean=is_mean, is_dispersion=is_dispersion,
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
