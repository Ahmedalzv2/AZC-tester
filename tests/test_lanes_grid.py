from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from lanes.grid import grid_levels, desired_ladder, orders_to_place


def test_grid_levels_span_band_evenly():
    lv = grid_levels(center=100.0, band_pct=0.10, n=5)
    assert len(lv) == 5
    assert lv[0] == 90.0 and lv[-1] == 110.0      # ±10% band
    assert lv[2] == 100.0                          # centre
    gaps = [round(lv[i + 1] - lv[i], 6) for i in range(4)]
    assert len(set(gaps)) == 1                     # evenly spaced


def test_ladder_flat_position_is_buys_only():
    # spot: with no holdings you can only place BUY limits below price
    lv = grid_levels(100.0, 0.10, 5)               # [90,95,100,105,110]
    ladder = desired_ladder(lv, price=100.0, per_level_qty=1.0, position_qty=0.0)
    assert all(o["side"] == "buy" for o in ladder)
    assert sorted(o["price"] for o in ladder) == [90.0, 95.0]   # below price only


def test_ladder_with_position_adds_sells_capped_by_holdings():
    lv = grid_levels(100.0, 0.10, 5)               # sells available at 105,110
    ladder = desired_ladder(lv, price=100.0, per_level_qty=1.0, position_qty=1.0)
    sells = [o for o in ladder if o["side"] == "sell"]
    assert len(sells) == 1                          # only 1 unit held -> 1 sell level
    assert sells[0]["price"] == 105.0               # nearest sell level first


def test_orders_to_place_skips_already_open():
    desired = [{"price": 90.0, "side": "buy", "qty": 1.0},
               {"price": 95.0, "side": "buy", "qty": 1.0}]
    open_orders = [{"price": 90.0, "side": "buy"}]
    todo = orders_to_place(desired, open_orders)
    assert todo == [{"price": 95.0, "side": "buy", "qty": 1.0}]


def test_orders_to_place_empty_when_all_open():
    desired = [{"price": 90.0, "side": "buy", "qty": 1.0}]
    assert orders_to_place(desired, [{"price": 90.0, "side": "buy"}]) == []
