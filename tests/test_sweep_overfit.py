"""The sweep must deflate its winner for the number of configs it tried.

Without this, the top row of any grid is the luckiest overfit dressed up with a
significant-looking p-value. The sweep result carries an `overfit` block whose
DSR answers: does the winner survive having been selected from N trials?
"""
from __future__ import annotations

from pathlib import Path

import pytest

from providers import DatasetRequest, get_provider
from sweep import run_sweep

FIX = Path("/root/apps/ict-autopilot/tests/fixtures")


def _sol_df():
    if not (FIX / "SOL-365d-Min15.json").exists():
        pytest.skip("AZC fixtures not mounted")
    return get_provider("azc_fixture").fetch(
        DatasetRequest(provider="azc_fixture", symbol="SOL-365d-Min15", years=10)
    ).df


def test_sweep_attaches_overfit_block():
    out = run_sweep(
        df=_sol_df(), strategy_name="azc_trend",
        grid={"don": [20, 30, 40]}, interval="15m", iterations=200,
    )
    ov = out["overfit"]
    assert ov["n_configs"] == 3
    for key in ("dsr", "psr_vs_zero", "sr_star", "survives_multiple_testing", "verdict"):
        assert key in ov
    assert 0.0 <= ov["dsr"] <= 1.0
    assert isinstance(ov["survives_multiple_testing"], bool)


def test_multiple_configs_deflate_below_raw():
    # With several trials the deflated DSR cannot exceed the un-deflated PSR.
    out = run_sweep(
        df=_sol_df(), strategy_name="azc_trend",
        grid={"don": [15, 20, 25, 30, 35, 40], "rr": [1.2, 1.6]}, interval="15m", iterations=200,
    )
    ov = out["overfit"]
    assert ov["n_configs"] == 12
    assert ov["sr_star"] >= 0.0
    assert ov["dsr"] <= ov["psr_vs_zero"] + 1e-9


def test_single_config_no_deflation():
    # No grid -> one trial -> no selection -> DSR equals PSR vs zero.
    out = run_sweep(
        df=_sol_df(), strategy_name="azc_trend",
        grid={}, interval="15m", iterations=200,
    )
    ov = out["overfit"]
    assert ov["n_configs"] == 1
    assert ov["sr_star"] == 0.0
    assert ov["dsr"] == pytest.approx(ov["psr_vs_zero"], abs=1e-9)
