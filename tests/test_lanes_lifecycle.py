from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from lanes.lifecycle import Track, evaluate


def test_blowup_kills_at_any_sample():
    v = evaluate(Track(n_trades=2, days=3, net_r=0.1, hac_t=0.5, max_dd=-0.25))
    assert v["action"] == "invalidate"
    assert "drawdown" in v["reason"].lower()


def test_drawdown_takes_precedence_over_profit():
    # profitable but blew through the DD limit -> still killed
    v = evaluate(Track(n_trades=40, days=60, net_r=0.5, hac_t=3.0, max_dd=-0.30))
    assert v["action"] == "invalidate" and "drawdown" in v["reason"].lower()


def test_no_edge_dump_after_min_trades():
    v = evaluate(Track(n_trades=35, days=20, net_r=-0.05, hac_t=-0.3, max_dd=-0.1))
    assert v["action"] == "invalidate" and "edge" in v["reason"].lower()


def test_no_edge_dump_after_min_days_even_if_flat():
    v = evaluate(Track(n_trades=8, days=50, net_r=0.0, hac_t=0.0, max_dd=-0.05))
    assert v["action"] == "invalidate"


def test_young_lane_continues():
    v = evaluate(Track(n_trades=5, days=10, net_r=-0.1, hac_t=-0.5, max_dd=-0.08))
    assert v["action"] == "continue"


def test_mature_profitable_lane_continues():
    v = evaluate(Track(n_trades=40, days=60, net_r=0.2, hac_t=2.5, max_dd=-0.12))
    assert v["action"] == "continue"
