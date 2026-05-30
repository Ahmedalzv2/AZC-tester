from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from report import build_report
from strategies import STRATEGIES
from strategies.custom_python import build as build_custom_python


@dataclass(slots=True)
class BacktestResult:
    metrics: dict[str, Any]
    curve: list[dict[str, Any]]
    trades: list[dict[str, Any]]


def _build_position(
    df: pd.DataFrame,
    strategy_name: str,
    params: dict[str, Any],
    custom_code: str | None,
) -> pd.Series:
    strategy = STRATEGIES.get(strategy_name)
    if not strategy:
        raise ValueError(f"Unknown strategy: {strategy_name}")
    if strategy.uses_custom_code:
        return build_custom_python(df, params, custom_code or "")
    if strategy.builder is None:
        raise ValueError(f"Strategy {strategy_name} has no builder")
    return strategy.builder(df, params)


BARS_PER_YEAR = {
    "1d": 252,
    "1wk": 52,
    "1mo": 12,
    "1h": 24 * 252,
    "15m": 4 * 24 * 252,
    "5m": 12 * 24 * 252,
}


def _trade_side(value: float) -> str:
    return "long" if value > 0 else "short"


def _trade_pnl_pct(side: str, entry_price: float, exit_price: float) -> float:
    if side == "long":
        return ((exit_price / entry_price) - 1) * 100
    return ((entry_price / exit_price) - 1) * 100


def run_backtest(
    df: pd.DataFrame,
    strategy_name: str,
    params: dict[str, Any],
    initial_cash: float = 10_000,
    fee_bps: float = 10,
    custom_code: str | None = None,
    interval: str = "1d",
) -> BacktestResult:
    if df.empty:
        raise ValueError("No data available for backtest")

    # AZC bracket strategies use a stop/target execution engine, not the
    # close-to-close position model below. Dispatch to it and adapt the result.
    spec = STRATEGIES.get(strategy_name)
    if spec is not None and getattr(spec, "execution", "position") == "bracket":
        from engine_bracket import run_bracket_backtest

        merged = {**spec.params, **(params or {})}
        # resample factor to 4h is auto-detected from the data's bar spacing
        # inside the engine, so any loaded interval (5m/15m/1h) works.
        metrics, curve, trade_rows = run_bracket_backtest(
            df=df.copy().sort_index(),
            params=merged,
            initial_cash=initial_cash,
            interval=interval,
            resample_per=None,
        )
        metrics["strategy"] = strategy_name
        return BacktestResult(metrics=metrics, curve=curve, trades=trade_rows)

    clean = df.copy().sort_index()
    close = clean["Close"].astype(float)
    position = _build_position(clean, strategy_name, params, custom_code).clip(-1, 1).fillna(0.0)
    shifted_position = position.shift(1).fillna(0.0)
    returns = close.pct_change().fillna(0.0)
    turnover = position.diff().abs().fillna(position.abs())
    fees = turnover * (fee_bps / 10_000)
    strategy_returns = (shifted_position * returns) - fees
    equity = initial_cash * (1 + strategy_returns).cumprod()
    drawdown = equity / equity.cummax() - 1

    # Dollar commission per bar: the fee fraction applied to prior equity. Summed
    # over a trade's bars this is the trade's commission; summed over all bars it
    # is the total — so gross_profit + gross_loss - commission == net_pnl exactly.
    prev_equity = equity.shift(1).fillna(float(initial_cash))
    dollar_fees = (fees * prev_equity).to_numpy()

    equity_arr = equity.to_numpy()
    pos_arr = position.to_numpy()
    shifted_arr = shifted_position.to_numpy()
    close_arr = close.to_numpy()
    index = clean.index

    trades: list[dict[str, Any]] = []
    cum_pnl = 0.0
    open_trade: dict[str, Any] | None = None

    def _close_trade(ot: dict[str, Any], exit_i: int) -> None:
        nonlocal cum_pnl
        entry_i = ot["entry_i"]
        # Base the trade on the equity just BEFORE the entry bar so the entry
        # commission (deducted on the entry bar) lands inside this trade's net
        # and commission, keeping gross = net + commission consistent.
        base_i = entry_i - 1
        equity_base = float(equity_arr[base_i]) if base_i >= 0 else float(initial_cash)
        equity_exit = float(equity_arr[exit_i])
        net_pnl = equity_exit - equity_base
        commission = float(dollar_fees[entry_i : exit_i + 1].sum())
        gross_pnl = net_pnl + commission
        notional = abs(ot["pos"]) * equity_base
        qty = notional / ot["entry_price"] if ot["entry_price"] else 0.0
        lo = base_i if base_i >= 0 else entry_i
        path = equity_arr[lo : exit_i + 1]
        runup = float(path.max() - equity_base) if path.size else 0.0
        drawdown_dollars = float(path.min() - equity_base) if path.size else 0.0
        cum_pnl += net_pnl
        pnl_pct = (net_pnl / notional) * 100 if notional else 0.0
        trades.append(
            {
                "entry_at": ot["entry_at"].isoformat(),
                "exit_at": index[exit_i].isoformat(),
                "side": ot["side"],
                "entry_price": round(ot["entry_price"], 4),
                "exit_price": round(float(close_arr[exit_i]), 4),
                "qty": round(qty, 6),
                "bars": int(exit_i - entry_i),
                "net_pnl": round(net_pnl, 2),
                "gross_pnl": round(gross_pnl, 2),
                "commission": round(commission, 2),
                "pnl_pct": round(pnl_pct, 3),
                "cum_pnl": round(cum_pnl, 2),
                "runup": round(runup, 2),
                "drawdown": round(drawdown_dollars, 2),
                "equity_after": round(equity_exit, 2),
            }
        )

    for i in range(len(index)):
        prev_pos = float(shifted_arr[i])
        current_pos = float(pos_arr[i])

        if open_trade is not None and (current_pos == 0 or np.sign(current_pos) != np.sign(prev_pos)):
            _close_trade(open_trade, i)
            open_trade = None

        if current_pos != 0 and (prev_pos == 0 or np.sign(current_pos) != np.sign(prev_pos)):
            open_trade = {
                "entry_i": i,
                "entry_at": index[i],
                "entry_price": float(close_arr[i]),
                "side": _trade_side(current_pos),
                "pos": current_pos,
            }

    # A position still open on the last bar is marked to the final close.
    if open_trade is not None:
        _close_trade(open_trade, len(index) - 1)

    total_return = (equity.iloc[-1] / initial_cash) - 1
    bars_per_year = BARS_PER_YEAR.get(interval, max(1, int(len(clean) / max(clean.index[-1].year - clean.index[0].year + 1, 1))))
    annualized = (equity.iloc[-1] / initial_cash) ** (bars_per_year / max(len(clean), 1)) - 1
    sharpe_denominator = strategy_returns.std(ddof=0)
    sharpe = 0.0 if sharpe_denominator == 0 else (strategy_returns.mean() / sharpe_denominator) * np.sqrt(bars_per_year)
    win_rate = 0.0
    if trades:
        win_rate = sum(1 for trade in trades if trade["net_pnl"] > 0) / len(trades)

    curve = []
    for i, idx in enumerate(index):
        curve.append(
            {
                "time": idx.isoformat(),
                "close": round(float(close_arr[i]), 4),
                "equity": round(float(equity_arr[i]), 2),
                "position": round(float(pos_arr[i]), 4),
                "drawdown": round(float(drawdown.iloc[i]) * 100, 3),
            }
        )

    report = build_report(
        curve=curve,
        trades=trades,
        initial_cash=float(initial_cash),
        bars_per_year=bars_per_year,
        commission_total=float(dollar_fees.sum()),
    )

    metrics = {
        "bars": int(len(clean)),
        "start": clean.index[0].isoformat(),
        "end": clean.index[-1].isoformat(),
        "initial_cash": float(initial_cash),
        "ending_equity": round(float(equity.iloc[-1]), 2),
        "total_return_pct": round(total_return * 100, 3),
        "annualized_return_pct": round(float(annualized) * 100, 3),
        "max_drawdown_pct": round(float(drawdown.min()) * 100, 3),
        "sharpe": round(float(sharpe), 3),
        "trade_count": int(len(trades)),
        "win_rate_pct": round(float(win_rate) * 100, 3),
        "exposure_pct": round(float(position.abs().mean()) * 100, 3),
        "fee_bps": float(fee_bps),
        "strategy": strategy_name,
        "strategy_params": params,
        "interval": interval,
        "report": report,
    }
    return BacktestResult(metrics=metrics, curve=curve, trades=trades[-500:])
