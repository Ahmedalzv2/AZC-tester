"""Sentinels for the equity cross-sectional momentum engine. The load-bearing one
is no-lookahead: a change to a FUTURE bar must not alter any past period's return."""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from equity_xsec_momentum import walk, stats


def _panel(n_assets=40, n_bars=400, seed=1):
    rng = random.Random(seed)
    by = {}
    for a in range(n_assets):
        c, series = 100.0, {}
        for t in range(n_bars):
            c *= 1 + rng.gauss(0.0003, 0.02)
            series[t] = c
        by[f"S{a}"] = series
    return by, list(by), n_bars


def test_no_lookahead():
    by, syms, n = _panel()
    base = walk(by, syms, n, lookback=252, skip=21, hold=21, frac=0.1, fee=0.0, mode="long_excess")
    rng = random.Random(99)
    by2 = {s: dict(v) for s, v in by.items()}
    for s in syms:  # corrupt only the final bar
        by2[s][n - 1] = rng.uniform(1, 1e6)
    pert = walk(by2, syms, n, lookback=252, skip=21, hold=21, frac=0.1, fee=0.0, mode="long_excess")
    assert base[:-1] == pert[:-1], "a future-bar change altered a past period -> LOOKAHEAD"


def test_skip_changes_signal():
    by, syms, n = _panel()
    a = walk(by, syms, n, lookback=252, skip=0, hold=21, frac=0.1, fee=0.0, mode="long_excess")
    b = walk(by, syms, n, lookback=252, skip=21, hold=21, frac=0.1, fee=0.0, mode="long_excess")
    assert a != b, "skip parameter had no effect on the formation window"


def test_fees_reduce_long_short():
    by, syms, n = _panel()
    free = sum(walk(by, syms, n, lookback=252, skip=21, hold=21, frac=0.1, fee=0.0, mode="long_short"))
    paid = sum(walk(by, syms, n, lookback=252, skip=21, hold=21, frac=0.1, fee=0.001, mode="long_short"))
    assert paid <= free, "fees did not reduce returns"


def test_stats_shape():
    by, syms, n = _panel()
    s = stats(walk(by, syms, n, lookback=252, skip=21, hold=21, frac=0.1, fee=0.0, mode="long_excess"), 21)
    assert set(s) >= {"n", "sharpe", "t", "oos_t", "mean_pct"}
