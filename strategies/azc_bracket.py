"""AZC crypto strategies — faithful bracket execution.

These mirror the live AZC research modules
(ict-autopilot/strategy-meanrev.mjs and strategy-trend-trail.mjs) and run on
the bracket engine, so the numbers here match the AZC repo's own backtester
(verified by tests/test_bracket_parity.py).

Fee model is exposed as params so you can A/B the one question that decides the
lane: maker fills (makerEntry/makerTp = true) vs the all-taker worst case
(both false). On the live MEXC tape SOL/XRP maker is ~free; the stop leg is
always taker. Default here is the conservative all-taker view.

Params are tuned for 4h bars. The engine auto-aggregates whatever interval you
load up to 4h (detected from the data's bar spacing), so 5m/15m/1h all work;
already-4h data is left as-is.
"""
from __future__ import annotations

from strategies.base import StrategySpec

# Mean-reversion: fade the 4h Donchian extreme, fixed RR target.
MEANREV = StrategySpec(
    name="azc_meanrev",
    label="AZC Mean-Rev (4h fade)",
    params={
        "don": 30, "atrMult": 2, "rr": 1.2, "atrN": 14, "fade": True,
        "makerEntry": False, "makerTp": False, "takerRate": 0.00075, "slipBps": 0,
        "riskPct": 0.005,
    },
    builder=None,
    execution="bracket",
)

# Trend: break the 4h Donchian channel, chandelier trailing stop, regime gate.
TREND = StrategySpec(
    name="azc_trend",
    label="AZC Trend+Trail (4h)",
    params={
        "don": 30, "atrMult": 2, "rr": 99, "trail": 3, "atrN": 14, "fade": False,
        "regimeN": 20, "erMin": 0.35,
        "makerEntry": False, "makerTp": False, "takerRate": 0.00075, "slipBps": 0,
        "riskPct": 0.005,
    },
    builder=None,
    execution="bracket",
)
