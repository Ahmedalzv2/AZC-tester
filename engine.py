from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

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
    prepared_bars: list[Any] | None = None,
) -> BacktestResult:
    if df is not None and df.empty:
        raise ValueError("No data available for backtest")

    # AZC bracket strategies use a stop/target execution engine, not the
    # close-to-close position model below. Dispatch to it and adapt the result.
    spec = STRATEGIES.get(strategy_name)
    if spec is not None and getattr(spec, "execution", "position") == "bracket":
        from engine_bracket import run_bracket_backtest

        merged = {**spec.params, **(params or {})}
        # resample factor to 4h is auto-detected from the data's bar spacing
        # inside the engine, so any loaded interval (5m/15m/1h) works.
        # prepared_bars (when a sweep pre-built them) skips the per-call
        # to_bars + resample; df is then unused.
        metrics, curve, trade_rows = run_bracket_backtest(
            df=df.copy().sort_index() if prepared_bars is None else None,
            params=merged,
            initial_cash=initial_cash,
            interval=interval,
            resample_per=None,
            bars=prepared_bars,
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

    trades = []
    open_trade: dict[str, Any] | None = None

    for idx in clean.index:
        prev_pos = float(shifted_position.loc[idx])
        current_pos = float(position.loc[idx])
        current_price = float(close.loc[idx])

        if open_trade is not None and (current_pos == 0 or np.sign(current_pos) != np.sign(prev_pos)):
            pnl_pct = _trade_pnl_pct(open_trade["side"], float(open_trade["entry_price"]), current_price)
            trades.append(
                {
                    "entry_at": open_trade["entry_at"].isoformat(),
                    "exit_at": idx.isoformat(),
                    "side": open_trade["side"],
                    "entry_price": round(float(open_trade["entry_price"]), 4),
                    "exit_price": round(current_price, 4),
                    "pnl_pct": round(pnl_pct, 3),
                    "equity_after": round(float(equity.loc[idx]), 2),
                }
            )
            open_trade = None

        if current_pos != 0 and (prev_pos == 0 or np.sign(current_pos) != np.sign(prev_pos)):
            open_trade = {
                "entry_at": idx,
                "entry_price": current_price,
                "side": _trade_side(current_pos),
            }

    total_return = (equity.iloc[-1] / initial_cash) - 1
    bars_per_year = BARS_PER_YEAR.get(interval, max(1, int(len(clean) / max(clean.index[-1].year - clean.index[0].year + 1, 1))))
    annualized = (equity.iloc[-1] / initial_cash) ** (bars_per_year / max(len(clean), 1)) - 1
    sharpe_denominator = strategy_returns.std(ddof=0)
    sharpe = 0.0 if sharpe_denominator == 0 else (strategy_returns.mean() / sharpe_denominator) * np.sqrt(bars_per_year)
    # Sortino: punish only downside deviation (returns below the 0% target),
    # annualized like Sharpe. Upside volatility is not risk.
    downside = strategy_returns[strategy_returns < 0]
    downside_dev = float(np.sqrt((downside.astype(float) ** 2).mean())) if len(downside) else 0.0
    sortino = 0.0 if downside_dev == 0 else (strategy_returns.mean() / downside_dev) * np.sqrt(bars_per_year)
    # Profit factor: gross win / gross loss across closed trades. >1 is net positive.
    gross_win = sum(t["pnl_pct"] for t in trades if t["pnl_pct"] > 0)
    gross_loss = -sum(t["pnl_pct"] for t in trades if t["pnl_pct"] < 0)
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
    win_rate = 0.0
    if trades:
        win_rate = sum(1 for trade in trades if trade["pnl_pct"] > 0) / len(trades)

    curve = []
    for idx, row in clean.iterrows():
        curve.append(
            {
                "time": idx.isoformat(),
                "close": round(float(row["Close"]), 4),
                "equity": round(float(equity.loc[idx]), 2),
                "position": round(float(position.loc[idx]), 4),
                "drawdown": round(float(drawdown.loc[idx]) * 100, 3),
            }
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
        "sortino": round(float(sortino), 3),
        "profit_factor": round(float(profit_factor), 3) if profit_factor != float("inf") else None,
        "trade_count": int(len(trades)),
        "win_rate_pct": round(float(win_rate) * 100, 3),
        "exposure_pct": round(float(position.abs().mean()) * 100, 3),
        "fee_bps": float(fee_bps),
        "strategy": strategy_name,
        "strategy_params": params,
        "interval": interval,
    }
    return BacktestResult(metrics=metrics, curve=curve, trades=trades[-200:])
