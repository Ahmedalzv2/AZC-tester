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


def test_assess_returns_valid_verdict_shape():
    bars = _trending_bars(1600, 0.001)
    is_bars, oos_bars = bars[:1100], bars[1100:]
    out = fitness.assess("donchian_break",
                         {"don": 20, "atrN": 14, "atrMult": 2.0, "trail": 3,
                          "erMin": 0.0, "regimeN": 20},
                         is_bars, oos_bars)
    assert out["verdict"] in ("real", "marginal", "noise")
    assert out["family"] == "donchian_break"
    assert set(out["oos"]) == {"n", "meanR", "t", "p", "holds"}
    assert out["deflation"].startswith("none")  # single hypothesis -> no deflation


def test_assess_rejects_unknown_family():
    import pytest as _pytest
    with _pytest.raises(ValueError):
        fitness.assess("not_a_family", {}, [], [])


def test_deflation_tightens_with_trials():
    # Marginal edge (t a few units) should pass a loose bar but fail a strict one
    # — the deflated alpha tightens the t-threshold, not an unsatisfiable p-floor.
    series = np.concatenate([np.full(50, 0.05), np.full(50, -0.01)])
    p = fitness._pvalue(series)
    t = fitness._tstat(series)
    loose = fitness._passes_gate(0.02, series.size, float(series.mean()), t, p, alpha_deflated=0.05)
    # alpha so tiny its critical-t exceeds this series' modest NW t-stat
    strict = fitness._passes_gate(0.02, series.size, float(series.mean()), t, p, alpha_deflated=1e-30)
    assert loose is True
    assert strict is False


def test_strong_signal_still_passes_under_heavy_deflation():
    # The bug: a genome with an enormous OOS t-stat (NW t ~ 8) was rejected once
    # ~100 lifetime trials accumulated, because the bootstrap p-value floors at
    # ~5e-4 while alpha_deflated kept shrinking below it. A continuous t-bar must
    # let a genuinely exceptional edge through no matter how deflated the alpha.
    strong = np.array([0.3] * 100 + [-0.1] * 20)
    assert fitness._passes_gate(
        is_score=float(strong.mean()), oos_n=strong.size, oos_mean=float(strong.mean()),
        oos_t=fitness._tstat(strong), oos_p=fitness._pvalue(strong),
        alpha_deflated=0.05 / 5000,  # ~5000 lifetime trials
    ) is True
