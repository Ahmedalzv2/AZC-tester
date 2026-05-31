"""Rich performance report builder.

Turns an equity curve plus a list of closed trades into the full report block
the dashboard renders: summary P&L, profit structure (gross profit / gross
loss / commission), risk-adjusted ratios (Sharpe, Sortino, max run-up), the
long / short split, the per-trade distribution histogram, and the aggregate
trade stats. Both execution engines (close-to-close in engine.py and the AZC
bracket engine in engine_bracket.py) feed the same shape into here so the
report looks identical no matter which lane produced the trades.

A "trade" handed in here must carry, at minimum, dollar-denominated truth:
    side        "long" | "short"
    net_pnl     dollars after commission
    gross_pnl   dollars before commission (net_pnl + commission)
    commission  dollars of fees attributed to the trade
    bars        bars held
    pnl_pct     trade return on deployed notional (percent)
Optional richer fields (entry/exit price+time, qty, run-up, drawdown,
cum_pnl) are passed straight through for the trade list.
"""
from __future__ import annotations

from typing import Any

import numpy as np


def _safe_div(num: float, den: float) -> float:
    return float(num / den) if den else 0.0


def _split_stats(trades: list[dict[str, Any]], deployed_capital: float) -> dict[str, Any]:
    """Aggregate one bucket of trades (all / long / short)."""
    n = len(trades)
    if not n:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": 0.0,
            "net_pnl": 0.0,
            "net_pnl_pct": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "profit_factor": 0.0,
            "avg_trade": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "largest_win": 0.0,
            "largest_loss": 0.0,
        }

    nets = np.asarray([float(t["net_pnl"]) for t in trades], dtype=float)
    gross = np.asarray([float(t.get("gross_pnl", t["net_pnl"])) for t in trades], dtype=float)
    wins = nets[nets > 0]
    losses = nets[nets < 0]
    gross_profit = float(gross[gross > 0].sum())
    gross_loss = float(gross[gross < 0].sum())
    net_pnl = float(nets.sum())
    return {
        "trades": int(n),
        "wins": int(wins.size),
        "losses": int(losses.size),
        "win_rate_pct": round(_safe_div(wins.size, n) * 100, 3),
        "net_pnl": round(net_pnl, 2),
        "net_pnl_pct": round(_safe_div(net_pnl, deployed_capital) * 100, 3),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(_safe_div(gross_profit, abs(gross_loss)), 3) if gross_loss else 0.0,
        "avg_trade": round(_safe_div(net_pnl, n), 2),
        "avg_win": round(_safe_div(float(wins.sum()), wins.size), 2) if wins.size else 0.0,
        "avg_loss": round(_safe_div(float(losses.sum()), losses.size), 2) if losses.size else 0.0,
        "largest_win": round(float(wins.max()), 2) if wins.size else 0.0,
        "largest_loss": round(float(losses.min()), 2) if losses.size else 0.0,
    }


def _equity_array(curve: list[dict[str, Any]]) -> np.ndarray:
    return np.asarray([float(p["equity"]) for p in curve], dtype=float)


def _max_runup(equity: np.ndarray) -> tuple[float, float]:
    """Largest gain above the running trough — the mirror of max drawdown."""
    if equity.size < 2:
        return 0.0, 0.0
    trough = np.minimum.accumulate(equity)
    safe = np.where(trough == 0.0, np.nan, trough)
    runup_pct = np.nanmax((equity / safe) - 1.0)
    runup_val = float(np.max(equity - trough))
    return float(np.nan_to_num(runup_pct)), runup_val


def _sortino(returns: np.ndarray, bars_per_year: int) -> float:
    r = returns[np.isfinite(returns)]
    if r.size < 2:
        return 0.0
    downside = np.minimum(r, 0.0)
    downside_dev = np.sqrt(np.mean(downside ** 2))
    if downside_dev == 0.0:
        return 0.0
    return float((r.mean() / downside_dev) * np.sqrt(bars_per_year))


def _distribution(trades: list[dict[str, Any]], bins: int = 14) -> dict[str, Any]:
    """Histogram of per-trade returns (%) — the P&L distribution chart."""
    if not trades:
        return {"edges": [], "counts": [], "colors": [], "avg_win_pct": 0.0, "avg_loss_pct": 0.0}
    pcts = np.asarray([float(t.get("pnl_pct", 0.0)) for t in trades], dtype=float)
    pcts = pcts[np.isfinite(pcts)]
    if pcts.size == 0:
        return {"edges": [], "counts": [], "colors": [], "avg_win_pct": 0.0, "avg_loss_pct": 0.0}
    lo, hi = float(pcts.min()), float(pcts.max())
    if lo == hi:
        lo, hi = lo - 0.5, hi + 0.5
    counts, edges = np.histogram(pcts, bins=bins, range=(lo, hi))
    centers = (edges[:-1] + edges[1:]) / 2.0
    colors = ["good" if c >= 0 else "bad" for c in centers]
    wins = pcts[pcts > 0]
    losses = pcts[pcts < 0]
    return {
        "edges": [round(float(e), 4) for e in edges],
        "centers": [round(float(c), 4) for c in centers],
        "counts": [int(c) for c in counts],
        "colors": colors,
        "avg_win_pct": round(float(wins.mean()), 3) if wins.size else 0.0,
        "avg_loss_pct": round(float(losses.mean()), 3) if losses.size else 0.0,
    }


def build_report(
    curve: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    initial_cash: float,
    bars_per_year: int,
    commission_total: float | None = None,
) -> dict[str, Any]:
    """Assemble the full report block from a curve + dollar-denominated trades."""
    equity = _equity_array(curve)
    ending_equity = float(equity[-1]) if equity.size else float(initial_cash)
    net_pnl = ending_equity - float(initial_cash)

    nets = np.asarray([float(t["net_pnl"]) for t in trades], dtype=float) if trades else np.asarray([])
    gross = np.asarray([float(t.get("gross_pnl", t["net_pnl"])) for t in trades], dtype=float) if trades else np.asarray([])
    comms = np.asarray([float(t.get("commission", 0.0)) for t in trades], dtype=float) if trades else np.asarray([])
    bars_held = np.asarray([float(t.get("bars", 0)) for t in trades], dtype=float) if trades else np.asarray([])

    gross_profit = float(gross[gross > 0].sum()) if gross.size else 0.0
    gross_loss = float(gross[gross < 0].sum()) if gross.size else 0.0
    commission = float(commission_total if commission_total is not None else comms.sum())

    # Per-bar equity returns drive the risk-adjusted ratios.
    if equity.size >= 2:
        prev = equity[:-1]
        safe_prev = np.where(prev == 0.0, np.nan, prev)
        step_returns = (equity[1:] / safe_prev) - 1.0
    else:
        step_returns = np.asarray([])

    std = step_returns.std(ddof=0) if step_returns.size else 0.0
    sharpe = float((step_returns.mean() / std) * np.sqrt(bars_per_year)) if std else 0.0
    sortino = _sortino(step_returns, bars_per_year)

    # Drawdown / run-up off the realized equity path.
    if equity.size:
        peak = np.maximum.accumulate(equity)
        safe_peak = np.where(peak == 0.0, np.nan, peak)
        dd_series = (equity / safe_peak) - 1.0
        max_dd_pct = float(np.nanmin(dd_series))
        max_dd_val = float(np.min(equity - peak))
    else:
        max_dd_pct, max_dd_val = 0.0, 0.0
    max_runup_pct, max_runup_val = _max_runup(equity)

    longs = [t for t in trades if t.get("side") == "long"]
    shorts = [t for t in trades if t.get("side") == "short"]

    wins = int((nets > 0).sum()) if nets.size else 0
    losses = int((nets < 0).sum()) if nets.size else 0
    total = len(trades)

    return {
        "initial_capital": round(float(initial_cash), 2),
        "ending_equity": round(ending_equity, 2),
        "net_pnl": round(net_pnl, 2),
        "net_pnl_pct": round(_safe_div(net_pnl, initial_cash) * 100, 3),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "commission": round(commission, 2),
        "profit_factor": round(_safe_div(gross_profit, abs(gross_loss)), 3) if gross_loss else 0.0,
        "max_drawdown_pct": round(max_dd_pct * 100, 3),
        "max_drawdown_value": round(max_dd_val, 2),
        "max_runup_pct": round(max_runup_pct * 100, 3),
        "max_runup_value": round(max_runup_val, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(_safe_div(wins, total) * 100, 3),
        "avg_trade": round(_safe_div(net_pnl, total), 2) if total else 0.0,
        "avg_win": round(_safe_div(float(nets[nets > 0].sum()), wins), 2) if wins else 0.0,
        "avg_loss": round(_safe_div(float(nets[nets < 0].sum()), losses), 2) if losses else 0.0,
        "largest_win": round(float(nets[nets > 0].max()), 2) if wins else 0.0,
        "largest_loss": round(float(nets[nets < 0].min()), 2) if losses else 0.0,
        "avg_bars_in_trade": round(float(bars_held.mean()), 1) if bars_held.size else 0.0,
        "expected_payoff": round(_safe_div(net_pnl, total), 2) if total else 0.0,
        "splits": {
            "all": _split_stats(trades, initial_cash),
            "long": _split_stats(longs, initial_cash),
            "short": _split_stats(shorts, initial_cash),
        },
        "distribution": _distribution(trades),
    }
