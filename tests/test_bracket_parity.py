"""Cross-validate the Python bracket engine against AZC's own JS simulator.

The oracle numbers below were produced by running
ict-autopilot/tests/backtest-meanrev.mjs `simulateMeanRev` on the shared
SOL-365d-Min15 fixture, resampled positionally to 4h (per=16). If this test
fails, the Python port has drifted from the source of truth — fix the port,
never the assertion.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine_bracket import Bar, bracket_metrics, resample_positional, simulate_bracket

FIX = Path("/root/apps/ict-autopilot/tests/fixtures")
PER_15M_TO_4H = 16


def load_fixture_4h(name: str, per: int) -> list[Bar]:
    raw = json.loads((FIX / name).read_text())
    base = [
        Bar(
            t=r["t"] if isinstance(r, dict) else r[0],
            o=float(r["o"] if isinstance(r, dict) else r[1]),
            h=float(r["h"] if isinstance(r, dict) else r[2]),
            l=float(r["l"] if isinstance(r, dict) else r[3]),
            c=float(r["c"] if isinstance(r, dict) else r[4]),
        )
        for r in raw
    ]
    return resample_positional(base, per)


@pytest.fixture(scope="module")
def sol_4h() -> list[Bar]:
    if not (FIX / "SOL-365d-Min15.json").exists():
        pytest.skip("AZC fixtures not mounted")
    return load_fixture_4h("SOL-365d-Min15.json", PER_15M_TO_4H)


def test_meanrev_all_taker_parity(sol_4h):
    trades = simulate_bracket(
        sol_4h,
        {"don": 30, "atrMult": 2, "rr": 1.2, "fade": True, "makerEntry": False, "makerTp": False, "takerRate": 0.00075, "slipBps": 0},
    )
    m = bracket_metrics(trades)
    assert m["n"] == 69
    assert m["winPct"] == pytest.approx(42.028985507, abs=1e-6)
    assert m["netR"] == pytest.approx(-0.110875031, abs=1e-9)
    assert m["totalR"] == pytest.approx(-7.650377134, abs=1e-6)
    assert m["maxDD"] == pytest.approx(14.192667267, abs=1e-6)


def test_meanrev_maker_parity(sol_4h):
    trades = simulate_bracket(
        sol_4h,
        {"don": 30, "atrMult": 2, "rr": 1.2, "fade": True, "makerEntry": True, "makerTp": True, "takerRate": 0.00075, "slipBps": 0},
    )
    m = bracket_metrics(trades)
    assert m["n"] == 69
    assert m["netR"] == pytest.approx(-0.086136774, abs=1e-9)
    assert m["totalR"] == pytest.approx(-5.943437434, abs=1e-6)


def test_trend_trail_all_taker_parity(sol_4h):
    trades = simulate_bracket(
        sol_4h,
        {"don": 30, "atrMult": 2, "rr": 99, "trail": 3, "fade": False, "makerEntry": False, "makerTp": False, "takerRate": 0.00075, "slipBps": 0},
    )
    m = bracket_metrics(trades)
    assert m["n"] == 56
    assert m["winPct"] == pytest.approx(37.5, abs=1e-6)
    assert m["netR"] == pytest.approx(0.056045735, abs=1e-9)
    assert m["totalR"] == pytest.approx(3.138561178, abs=1e-6)
    assert m["maxDD"] == pytest.approx(14.280074741, abs=1e-6)


def test_full_pipeline_auto_resamples_15m_to_4h_and_matches_oracle():
    """End-to-end: provider loads native-15m bars, dispatch auto-detects the
    4h aggregation factor, and the bracket engine reproduces the oracle. This
    guards the auto-resample path the API actually uses."""
    if not (FIX / "SOL-365d-Min15.json").exists():
        pytest.skip("AZC fixtures not mounted")
    from engine import run_backtest
    from providers import DatasetRequest, get_provider

    resp = get_provider("azc_fixture").fetch(DatasetRequest(provider="azc_fixture", symbol="SOL-365d-Min15", years=10))
    # native 15m bars in, no pre-resampling
    assert (resp.df.index[1] - resp.df.index[0]).total_seconds() == pytest.approx(15 * 60, abs=1)

    # Default azc_trend carries the live regime gate (erMin=0.35). JS oracle
    # (regime-gated trend+trail, all-taker): n=35, netR/trade +0.16809.
    result = run_backtest(df=resp.df, strategy_name="azc_trend", params={}, initial_cash=10_000, interval="15m")
    assert result.metrics["trade_count"] == 35
    assert result.metrics["net_r_per_trade"] == pytest.approx(0.1681, abs=5e-4)
    assert result.metrics["total_r"] == pytest.approx(5.883, abs=2e-3)
    assert result.metrics["execution"] == "bracket"
    assert result.metrics["fee_model"] == "all-taker"

    # Disabling the gate reproduces the ungated oracle (n=56) — proves the
    # regime gate is the only difference, and the engine math is unchanged.
    ungated = run_backtest(df=resp.df, strategy_name="azc_trend", params={"erMin": 0}, initial_cash=10_000, interval="15m")
    assert ungated.metrics["trade_count"] == 56
    assert ungated.metrics["net_r_per_trade"] == pytest.approx(0.056, abs=5e-4)
