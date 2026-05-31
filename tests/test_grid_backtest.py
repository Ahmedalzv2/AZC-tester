"""Tests for the grid backtester — fill logic, fee accounting, no lookahead."""
import math

import pytest

from grid_backtest import simulate_grid


def _bars(closes: list[float]) -> list[dict]:
    """OHLC bars from a close path; o=prev close, h/l span the move (no extra wick)."""
    out = []
    prev = closes[0]
    for c in closes:
        out.append({"t": 0, "o": prev, "h": max(prev, c), "l": min(prev, c), "c": c, "v": 1})
        prev = c
    return out


def _oscillate(base: float, amp: float, n: int) -> list[float]:
    return [base * (1 + amp * math.sin(i / 3.0)) for i in range(n)]


def test_no_lookahead_past_equity_is_immune_to_future_bars():
    """Equity through bar k must not change when bars after k are mutated."""
    closes = _oscillate(100.0, 0.08, 400)
    bars = _bars(closes)
    full = simulate_grid(bars, step=0.02, max_lots=20, fee=0.0, sample_bars=10)

    # Mutate the tail: 10x the price after the midpoint.
    k = 200
    tampered = [dict(b) for b in bars]
    for i in range(k, len(tampered)):
        for key in ("o", "h", "l", "c"):
            tampered[i][key] *= 10.0
    tamp = simulate_grid(tampered, step=0.02, max_lots=20, fee=0.0, sample_bars=10)

    # Curve points sampled before bar k must be identical (those used only past data).
    pre = k // 10
    for a, b in zip(full["curve"][:pre], tamp["curve"][:pre]):
        assert a["equity"] == pytest.approx(b["equity"], rel=1e-12)


def test_higher_fees_never_help():
    closes = _oscillate(100.0, 0.06, 600)
    bars = _bars(closes)
    maker = simulate_grid(bars, step=0.015, max_lots=20, fee=0.0)
    taker = simulate_grid(bars, step=0.015, max_lots=20, fee=0.00075)
    assert taker["total_return"] <= maker["total_return"] + 1e-9


def test_oscillation_books_grid_profit_at_zero_fee():
    """A pure oscillation around base should net positive at zero fee (churn edge)."""
    closes = _oscillate(100.0, 0.06, 800)
    bars = _bars(closes)
    res = simulate_grid(bars, step=0.015, max_lots=20, fee=0.0)
    assert res["total_return"] > 0.0


def test_pure_downtrend_loses_the_bag():
    """A monotone crash leaves a fully-accumulated bag → loss, not a free lunch."""
    closes = [100.0 * (0.99 ** i) for i in range(300)]
    bars = _bars(closes)
    res = simulate_grid(bars, step=0.02, max_lots=30, fee=0.0)
    assert res["total_return"] < 0.0


def test_curve_starts_at_capital():
    bars = _bars(_oscillate(50.0, 0.05, 100))
    res = simulate_grid(bars, step=0.02, max_lots=10, fee=0.0)
    assert res["curve"][0]["equity"] == pytest.approx(1000.0)
