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


def _passes_gate(is_score, oos_n, oos_mean, oos_t, oos_p, alpha_deflated) -> bool:
    return bool(
        oos_n >= MIN_OOS_TRADES and oos_mean > 0 and is_score > 0
        and oos_t >= 2.0 and oos_p < alpha_deflated
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
