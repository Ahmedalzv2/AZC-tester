from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from evolab.publish import build_equity_curve


def test_curve_has_required_chart_fields():
    curve = build_equity_curve([0.5, -0.2, 0.3], risk_pct=0.01)
    assert len(curve) == 3
    assert set(curve[0]) == {"time", "equity", "drawdown"}   # what renderCharts maps over
    assert [r["time"] for r in curve] == [1, 2, 3]


def test_equity_moves_with_net_r_and_drawdown_nonpositive():
    curve = build_equity_curve([1.0, -1.0, -1.0], risk_pct=0.01)
    assert curve[0]["equity"] > 100.0          # a win lifts equity
    assert curve[-1]["equity"] < curve[0]["equity"]
    assert all(r["drawdown"] <= 0.0 for r in curve)   # drawdown is peak-to-trough, never positive


def test_empty_trades_gives_empty_curve():
    assert build_equity_curve([], risk_pct=0.01) == []
