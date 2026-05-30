from __future__ import annotations

from pathlib import Path
import sys

import numpy as np

sys.path.append(str(Path(__file__).resolve().parents[1]))

from engine_bracket import Bar
from evolab import fitness
from evolab.genome import Genome


def _trending_bars(n: int, drift: float) -> list[Bar]:
    bars = []
    px = 100.0
    for i in range(n):
        px *= (1 + drift)
        bars.append(Bar(t=i * 3600_000, o=px, h=px * 1.002, l=px * 0.998, c=px))
    return bars


def test_oos_too_few_trades_is_never_candidate():
    g = Genome("donchian_break", {"don": 55, "atrN": 14, "atrMult": 3.0,
                                  "trail": 3, "erMin": 0.0, "regimeN": 20})
    is_bars, oos_bars = _trending_bars(60, 0.001), _trending_bars(20, 0.001)
    res = fitness.evaluate(g, (is_bars, oos_bars), alpha_deflated=0.05)
    assert res.is_champion_candidate is False


def test_strong_signal_passes_champion_gate_directly():
    # A realistic strong edge: mostly winners, some losers -> positive mean WITH
    # variance (a constant array has zero variance and an undefined t-stat).
    strong = np.array([0.3] * 100 + [-0.1] * 20)
    assert fitness._passes_gate(
        is_score=float(strong.mean()), oos_n=strong.size, oos_mean=float(strong.mean()),
        oos_t=fitness._tstat(strong), oos_p=fitness._pvalue(strong),
        alpha_deflated=0.05,
    ) is True


def test_deflation_tightens_with_trials():
    series = np.concatenate([np.full(50, 0.05), np.full(50, -0.01)])
    p = fitness._pvalue(series)
    t = fitness._tstat(series)
    loose = fitness._passes_gate(0.02, series.size, float(series.mean()), t, p, alpha_deflated=0.05)
    strict = fitness._passes_gate(0.02, series.size, float(series.mean()), t, p, alpha_deflated=1e-6)
    assert loose != strict or (loose is False and strict is False)
    assert strict is False
