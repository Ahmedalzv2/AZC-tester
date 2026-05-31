"""Tests for the pure IBKR micro-futures planner, mapping, and paper-guard."""
import pytest

from execution.ibkr_futures import (
    CONTRACT_MAP, UNMAPPABLE, assert_paper_account, map_targets, plan_futures_orders,
)


def test_map_targets_splits_mappable_and_gap():
    targets = {"SPY": 0.2, "QQQ": 0.1, "GLD": 0.15, "EFA": 0.1, "TLT": 0.2}
    mapped, gap = map_targets(targets)
    assert mapped == {"MES": 0.2, "MNQ": 0.1, "MGC": 0.15}
    assert gap == ["EFA", "TLT"]


def test_map_targets_drops_zero_weight_unmappable():
    mapped, gap = map_targets({"SPY": 0.3, "EEM": 0.0})
    assert mapped == {"MES": 0.3}
    assert gap == []  # zero-weight unmappable isn't a real coverage gap


def test_plan_buys_to_target_contracts():
    # MES mult 5; price 5900 -> $29,500/contract. 20% of $1M = $200k -> ~6.78 -> 7.
    orders = plan_futures_orders({"MES": 0.2}, equity=1_000_000,
                                 prices={"MES": 5900.0}, positions={})
    assert orders == [{"symbol": "MES", "action": "buy", "contracts": 7}]


def test_plan_sells_when_overweight():
    orders = plan_futures_orders({"MES": 0.0}, equity=1_000_000,
                                 prices={"MES": 5900.0}, positions={"MES": 7})
    assert orders == [{"symbol": "MES", "action": "sell", "contracts": 7}]


def test_plan_skips_sub_one_contract_moves():
    # 0.1% of $100k = $100 target vs a $29.5k contract -> rounds to 0, no order.
    orders = plan_futures_orders({"MES": 0.001}, equity=100_000,
                                 prices={"MES": 5900.0}, positions={})
    assert orders == []


def test_plan_skips_when_price_missing():
    orders = plan_futures_orders({"MES": 0.2}, equity=1_000_000,
                                 prices={}, positions={})
    assert orders == []


def test_small_equity_rounds_micro_legs_to_zero():
    # $5k equity, 10% weight = $500 vs $29.5k/contract -> 0 contracts (real constraint).
    orders = plan_futures_orders({"MES": 0.1}, equity=5_000,
                                 prices={"MES": 5900.0}, positions={})
    assert orders == []


def test_paper_guard_accepts_DU_rejects_live():
    assert_paper_account("DU1234567")  # no raise
    with pytest.raises(RuntimeError, match="not a paper"):
        assert_paper_account("U1234567")


def test_contract_map_covers_liquid_core_only():
    assert set(CONTRACT_MAP) == {"SPY", "QQQ", "IWM", "GLD", "USO", "SLV"}
    assert UNMAPPABLE == {"EFA", "EEM", "DBC", "TLT"}
