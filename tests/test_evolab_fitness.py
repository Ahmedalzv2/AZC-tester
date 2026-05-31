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
        is_mean=float(strong.mean()), oos_n=strong.size, oos_mean=float(strong.mean()),
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
        is_mean=float(strong.mean()), oos_n=strong.size, oos_mean=float(strong.mean()),
        oos_t=fitness._tstat(strong), oos_p=fitness._pvalue(strong),
        alpha_deflated=0.05 / 5000,  # ~5000 lifetime trials
    ) is True


# --- selection fitness = cross-fold robustness (optimize for OOS persistence) ---


def test_stability_score_penalizes_dispersion():
    # Same in-sample mean, different temporal consistency across folds. The steady
    # edge (real-looking) must outscore the spiky one (one lucky streak), because
    # the spiky edge is the kind that dies out of sample.
    steady = np.full(40, 0.1)
    spiky = np.concatenate([np.full(20, 0.4), np.full(20, -0.2)])
    assert abs(float(steady.mean()) - float(spiky.mean())) < 1e-9  # equal means
    assert fitness._stability_score(steady) > fitness._stability_score(spiky)


def test_stability_score_never_exceeds_mean():
    # The penalty (lambda * dispersion, dispersion >= 0) can only lower the score.
    spiky = np.concatenate([np.full(20, 0.4), np.full(20, -0.2)])
    assert fitness._stability_score(spiky) <= float(spiky.mean()) + 1e-12


def test_stability_score_falls_back_to_mean_when_thin():
    # Fewer than 2 folds with enough trades -> no coverage to judge stability, so
    # fall back to the plain mean (no penalty).
    thin = np.array([0.1, 0.2, 0.3])
    assert fitness._stability_score(thin) == float(thin.mean())


def test_stability_score_empty_is_neg_inf():
    assert fitness._stability_score(np.array([])) == float("-inf")


def test_evaluate_exposes_is_mean_and_dispersion():
    bars = _trending_bars(1600, 0.001)
    g = Genome("donchian_break", {"don": 20, "atrN": 14, "atrMult": 2.0,
                                  "trail": 3, "erMin": 0.0, "regimeN": 20})
    r = fitness.evaluate(g, (bars[:1100], bars[1100:]), alpha_deflated=0.05)
    assert hasattr(r, "is_mean")
    assert hasattr(r, "is_dispersion")
    if r.is_n > 0:
        # selection score never exceeds the raw IS mean (stability penalty >= 0)
        assert r.is_score <= r.is_mean + 1e-9
        assert r.is_dispersion >= 0.0


def test_gate_keys_off_raw_is_positivity():
    # The champion gate's first arg is the raw IS mean: a positive IS mean with a
    # passing OOS t passes; a non-positive IS mean fails regardless of OOS.
    assert fitness._passes_gate(0.01, 100, 0.2, 2.5, 0.001, 0.05) is True
    assert fitness._passes_gate(-0.01, 100, 0.2, 2.5, 0.001, 0.05) is False
