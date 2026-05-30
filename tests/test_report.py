from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from report import build_report


def _curve(equities: list[float]) -> list[dict]:
    return [{"time": f"2024-01-{i + 1:02d}T00:00:00", "equity": e} for i, e in enumerate(equities)]


def _trade(side: str, net: float, commission: float, bars: int, pnl_pct: float) -> dict:
    return {
        "side": side,
        "net_pnl": net,
        "gross_pnl": net + commission,
        "commission": commission,
        "bars": bars,
        "pnl_pct": pnl_pct,
    }


def test_profit_structure_identity_holds() -> None:
    # gross_profit + gross_loss - commission must equal net_pnl exactly.
    trades = [
        _trade("long", 100.0, 1.0, 5, 1.0),
        _trade("short", -40.0, 1.0, 3, -0.4),
        _trade("long", 60.0, 2.0, 8, 0.6),
    ]
    curve = _curve([1000.0, 1100.0, 1060.0, 1120.0])
    rep = build_report(curve, trades, initial_cash=1000.0, bars_per_year=252)

    assert rep["net_pnl"] == 120.0  # 1120 - 1000
    identity = rep["gross_profit"] + rep["gross_loss"] - rep["commission"]
    assert round(identity, 6) == rep["net_pnl"]


def test_long_short_split_partitions_trades() -> None:
    trades = [
        _trade("long", 100.0, 0.0, 5, 1.0),
        _trade("short", -40.0, 0.0, 3, -0.4),
        _trade("short", 30.0, 0.0, 4, 0.3),
    ]
    curve = _curve([1000.0, 1100.0, 1060.0, 1090.0])
    rep = build_report(curve, trades, initial_cash=1000.0, bars_per_year=252)

    assert rep["splits"]["all"]["trades"] == 3
    assert rep["splits"]["long"]["trades"] == 1
    assert rep["splits"]["short"]["trades"] == 2
    assert rep["splits"]["long"]["net_pnl"] == 100.0
    assert rep["splits"]["short"]["net_pnl"] == -10.0
    # win-rate: 1 of 1 longs, 1 of 2 shorts
    assert rep["splits"]["long"]["win_rate_pct"] == 100.0
    assert rep["splits"]["short"]["win_rate_pct"] == 50.0


def test_win_loss_counts_and_ratios() -> None:
    trades = [
        _trade("long", 50.0, 0.0, 2, 0.5),
        _trade("long", -20.0, 0.0, 2, -0.2),
        _trade("long", -10.0, 0.0, 2, -0.1),
    ]
    curve = _curve([1000.0, 1050.0, 1030.0, 1020.0])
    rep = build_report(curve, trades, initial_cash=1000.0, bars_per_year=252)

    assert rep["wins"] == 1
    assert rep["losses"] == 2
    assert rep["largest_win"] == 50.0
    assert rep["largest_loss"] == -20.0
    assert rep["profit_factor"] == round(50.0 / 30.0, 3)
    assert rep["avg_bars_in_trade"] == 2.0


def test_empty_trades_are_safe() -> None:
    rep = build_report(_curve([1000.0, 1000.0]), [], initial_cash=1000.0, bars_per_year=252)
    assert rep["total_trades"] == 0
    assert rep["profit_factor"] == 0.0
    assert rep["distribution"]["counts"] == []
