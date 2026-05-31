from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from lanes import perp_sim
from lanes.lifecycle import Track, evaluate


def test_simulate_perp_returns_a_track():
    t = perp_sim.simulate_perp("BTC")
    assert isinstance(t, Track)
    assert t.n_trades >= 0 and t.days > 0


def test_funding_haircut_lowers_net_r():
    # more funding => strictly worse net_r (it's a cost)
    low = perp_sim.simulate_perp("BTC", funding_r_per_trade=0.0)
    high = perp_sim.simulate_perp("BTC", funding_r_per_trade=0.20)
    assert high.net_r < low.net_r


def test_losing_perp_track_is_invalidated():
    # a matured, negative-net track must be dumped by the lifecycle
    v = evaluate(Track(n_trades=50, days=400, net_r=-0.08, hac_t=-0.4, max_dd=-0.15))
    assert v["action"] == "invalidate"
