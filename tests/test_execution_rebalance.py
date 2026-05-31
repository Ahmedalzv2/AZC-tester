from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from execution.rebalance import plan_orders


def test_flat_to_target_buys_each_weight():
    orders = plan_orders({"SPY": 0.5, "QQQ": 0.3}, equity=100_000, positions={})
    by = {o["symbol"]: o for o in orders}
    assert by["SPY"] == {"symbol": "SPY", "action": "buy", "notional": 50_000.0}
    assert by["QQQ"] == {"symbol": "QQQ", "action": "buy", "notional": 30_000.0}


def test_within_threshold_is_noop():
    # already at target (50k) within the $50 threshold -> no order
    orders = plan_orders({"SPY": 0.5}, equity=100_000, positions={"SPY": 49_980.0},
                         min_trade_usd=50.0)
    assert orders == []


def test_reduce_position_sells_the_delta():
    orders = plan_orders({"SPY": 0.2}, equity=100_000, positions={"SPY": 50_000.0})
    assert orders == [{"symbol": "SPY", "action": "sell", "notional": 30_000.0}]


def test_dropped_symbol_is_closed_fully():
    # SPY no longer in targets but still held -> close, not a notional sell
    orders = plan_orders({"QQQ": 1.0}, equity=100_000, positions={"SPY": 12_345.0})
    by = {o["symbol"]: o for o in orders}
    assert by["SPY"] == {"symbol": "SPY", "action": "close"}
    assert by["QQQ"]["action"] == "buy"


def test_zero_weight_held_is_closed():
    orders = plan_orders({"SPY": 0.0}, equity=100_000, positions={"SPY": 9_000.0})
    assert orders == [{"symbol": "SPY", "action": "close"}]


def test_no_orders_when_flat_and_no_targets():
    assert plan_orders({}, equity=100_000, positions={}) == []
