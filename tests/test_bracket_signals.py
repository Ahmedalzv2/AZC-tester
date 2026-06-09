"""The generic signal simulator must reproduce the canonical engine on the
Donchian entry, else the shared exit/fee machinery has drifted."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bracket_signals import SIGNALS, break_retest, donchian_break, donchian_fade, simulate_signal
from engine_bracket import Bar, bracket_metrics, resample_positional, simulate_bracket


def _bars(ohlc):
    """Build a Bar list from (o,h,l,c) tuples with sequential hourly stamps."""
    return [Bar(t=k * 3600_000, o=o, h=h, l=l, c=c) for k, (o, h, l, c) in enumerate(ohlc)]


# break_retest params used across the unit tests below.
_BR = {"brL": 5, "brW": 3, "brTolAtr": 0.5, "atrN": 3}


# brL=5 + brW=3 → the earliest decidable bar is index 8 (level window needs
# L bars before a breakout that sits within the W-bar window). Confirmation
# lands on index 8 in every pattern below.
def _long_pattern():
    # 6 flat bars (resistance = high 100), a breakout bar that clears it, then a
    # pullback drifting down to the level, then a confirmation bar whose low taps
    # the level and closes bullish back above it.
    return _bars([
        (99, 100, 98, 99), (99, 100, 98, 99), (99, 100, 98, 99),
        (99, 100, 98, 99), (99, 100, 98, 99), (99, 100, 98, 99),  # 0..5 resistance = 100
        (99, 105, 99, 104),                        # 6  breakout (close 104 > 100)
        (103, 104, 101, 101),                      # 7  pullback toward level
        (101, 103, 99.8, 102),                     # 8  retest tap + bullish reclaim
    ])


def test_break_retest_fires_long_on_reclaim():
    bars = _long_pattern()
    assert break_retest(bars, 8, _BR) == "long"


def test_break_retest_no_signal_without_retest():
    # Same breakout, but price never comes back down to the level on bar 8.
    bars = _bars([
        (99, 100, 98, 99), (99, 100, 98, 99), (99, 100, 98, 99),
        (99, 100, 98, 99), (99, 100, 98, 99), (99, 100, 98, 99),
        (99, 105, 99, 104),
        (104, 106, 103, 105),
        (105, 108, 104, 107),   # 8  no pullback to 100 → no retest
    ])
    assert break_retest(bars, 8, _BR) is None


def test_break_retest_no_signal_without_breakout():
    # Flat range, nothing ever broke the level.
    bars = _bars([(99, 100, 98, 99)] * 9)
    assert break_retest(bars, 8, _BR) is None


def test_break_retest_fires_short_on_breakdown_reclaim():
    # Mirror: support = low 100, a breakdown bar, pullback up, bearish reject.
    bars = _bars([
        (101, 102, 100, 101), (101, 102, 100, 101), (101, 102, 100, 101),
        (101, 102, 100, 101), (101, 102, 100, 101), (101, 102, 100, 101),  # 0..5 support = 100
        (101, 101, 95, 96),                            # 6  breakdown (close 96 < 100)
        (97, 99, 96, 99),                              # 7  pullback up toward level
        (99, 100.2, 97, 98),                           # 8  retest tap + bearish reject
    ])
    assert break_retest(bars, 8, _BR) == "short"

FIX = Path("/root/apps/ict-autopilot/tests/fixtures")


def _load(name, per):
    raw = json.loads((FIX / name).read_text())
    base = [Bar(t=(r["t"] if isinstance(r, dict) else r[0]),
                o=float(r["o"] if isinstance(r, dict) else r[1]),
                h=float(r["h"] if isinstance(r, dict) else r[2]),
                l=float(r["l"] if isinstance(r, dict) else r[3]),
                c=float(r["c"] if isinstance(r, dict) else r[4])) for r in raw]
    return resample_positional(base, per)


@pytest.fixture(scope="module")
def sol_4h():
    if not (FIX / "SOL-365d-Min15.json").exists():
        pytest.skip("fixtures not mounted")
    return _load("SOL-365d-Min15.json", 16)


def test_generic_matches_canonical_trend(sol_4h):
    p = {"don": 30, "atrMult": 2, "rr": 99, "trail": 3, "atrN": 14,
         "makerEntry": False, "makerTp": False, "takerRate": 0.00075}
    canon = bracket_metrics(simulate_bracket(sol_4h, {**p, "fade": False}))
    generic = bracket_metrics(simulate_signal(sol_4h, donchian_break, p))
    assert generic["n"] == canon["n"]
    assert generic["netR"] == pytest.approx(canon["netR"], abs=1e-9)


def test_generic_matches_canonical_fade(sol_4h):
    p = {"don": 30, "atrMult": 2, "rr": 1.2, "atrN": 14,
         "makerEntry": False, "makerTp": False, "takerRate": 0.00075}
    canon = bracket_metrics(simulate_bracket(sol_4h, {**p, "fade": True}))
    generic = bracket_metrics(simulate_signal(sol_4h, donchian_fade, p))
    assert generic["n"] == canon["n"]
    assert generic["netR"] == pytest.approx(canon["netR"], abs=1e-9)


def test_all_signals_run_without_error(sol_4h):
    p = {"don": 20, "atrMult": 2, "rr": 1.5, "atrN": 14, "fast": 10, "slow": 30,
         "mom": 20, "rsi_n": 14, "bb_n": 20, "bb_k": 2}
    for name, fn in SIGNALS.items():
        trades = simulate_signal(sol_4h, fn, p)
        assert isinstance(trades, list)
