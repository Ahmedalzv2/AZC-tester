"""Sentinel tests for the standalone MEXC daily trend engine.

The load-bearing one is `test_no_lookahead`: if scrambling FUTURE bars changes a
past entry decision, the engine is peeking at the future and every result is a lie.
"""
import math
import random

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mexc_trend_hunt import Bar, Params, atr, backtest, backtest_fade, eff_ratio, hac_t, signals


def _synth(n=400, seed=1):
    rng = random.Random(seed)
    bars, c = [], 100.0
    for t in range(n):
        c *= 1 + rng.gauss(0.001, 0.03)
        o = c * (1 + rng.gauss(0, 0.005))
        hi = max(o, c) * (1 + abs(rng.gauss(0, 0.01)))
        lo = min(o, c) * (1 - abs(rng.gauss(0, 0.01)))
        bars.append(Bar(t * 86400, o, hi, lo, c))
    return bars


def test_no_lookahead():
    bars = _synth()
    p = Params()
    sig = signals(bars, p)
    assert sig, "expected some signals on synthetic data"
    k = len(bars) // 2
    # Scramble everything strictly after bar k.
    rng = random.Random(99)
    scrambled = list(bars[: k + 1])
    for t in range(k + 1, len(bars)):
        scrambled.append(Bar(t * 86400, rng.uniform(1, 1e6), rng.uniform(1, 1e6),
                             rng.uniform(1, 1e6), rng.uniform(1, 1e6)))
    sig2 = signals(scrambled, p)
    past = [s for s in sig if s[0] <= k]
    past2 = [s for s in sig2 if s[0] <= k]
    assert past == past2, "future bars changed a past decision -> LOOKAHEAD"


def test_fees_reduce_returns():
    bars = _synth()
    p = Params()
    free = backtest(bars, p, 0.0)
    taker = backtest(bars, p, 0.00075)
    assert len(free) == len(taker)  # fees don't change which trades fire
    assert sum(taker) < sum(free), "fees must reduce total netR"


def test_fade_fees_reduce_returns():
    bars = _synth()
    p = Params()
    free = backtest_fade(bars, p, 0.0)
    taker = backtest_fade(bars, p, 0.00075)
    assert len(free) == len(taker)
    # fees must subtract in the fade direction too (not flip to a gain)
    assert sum(taker) < sum(free)


def test_atr_uses_only_past():
    bars = _synth()
    a = atr(bars, 14)
    bars2 = list(bars)
    bars2[-1] = Bar(bars[-1].ts, 1e9, 1e9, 1e9, 1e9)
    a2 = atr(bars2, 14)
    for i in range(len(bars) - 1):
        if math.isnan(a[i]) and math.isnan(a2[i]):
            continue
        assert a[i] == a2[i], "ATR at past bars changed when only the last bar changed"


def test_hac_t_zero_mean_is_small():
    rng = random.Random(7)
    x = [rng.gauss(0, 1) for _ in range(500)]
    assert abs(hac_t(x)) < 3.0


def test_eff_ratio_bounds():
    bars = _synth()
    for i in range(50, len(bars)):
        er = eff_ratio(bars, i, 20)
        assert 0.0 <= er <= 1.0 + 1e-9
