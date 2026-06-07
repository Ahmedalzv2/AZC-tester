"""The generic signal simulator must reproduce the canonical engine on the
Donchian entry, else the shared exit/fee machinery has drifted."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bracket_signals import SIGNALS, donchian_break, donchian_fade, simulate_signal
from engine_bracket import Bar, bracket_metrics, resample_positional, simulate_bracket

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
