"""Tests for the proven-edge decay tripwire's pure verdict logic.

The watcher re-runs the portfolio search monthly and flags fade. It MONITORS;
it never retunes prod. These tests pin the verdict thresholds on synthetic
search reports (no network, no search run)."""
from __future__ import annotations

from proven_decay_watch import decay_verdict


def _report(prod_t, prod_sh, best_t, dsr=0.9):
    return {
        "prod": {"oos": {"hac_t": prod_t, "sharpe_ann": prod_sh}},
        "best_by_oos": {"oos": {"hac_t": best_t, "sharpe_ann": best_t * 0.3}},
        "deflated": {"dsr": dsr},
    }


def test_healthy_when_prod_strong_and_best_clears_two():
    v = decay_verdict(_report(prod_t=1.9, prod_sh=0.58, best_t=2.17))
    assert v["status"] == "healthy"
    assert v["prod_oos_t"] == 1.9 and v["best_oos_t"] == 2.17


def test_softening_when_prod_t_dips_or_best_below_two():
    assert decay_verdict(_report(prod_t=1.2, prod_sh=0.4, best_t=2.1))["status"] == "softening"
    assert decay_verdict(_report(prod_t=1.9, prod_sh=0.5, best_t=1.7))["status"] == "softening"


def test_decayed_when_prod_negative_or_best_collapses():
    assert decay_verdict(_report(prod_t=0.5, prod_sh=-0.05, best_t=1.5))["status"] == "decayed"
    assert decay_verdict(_report(prod_t=0.8, prod_sh=0.2, best_t=0.6))["status"] == "decayed"


def test_verdict_carries_dsr_through():
    v = decay_verdict(_report(prod_t=1.9, prod_sh=0.58, best_t=2.17, dsr=0.889))
    assert v["dsr"] == 0.889
