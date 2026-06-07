"""Forward paper-trade tracker for the diversified ETF trend portfolio.

The 100-year backtest proves the edge historically; this accrues a LIVE,
out-of-sample track record going forward (the un-overfittable confirmation, same
philosophy as the crypto shadow lane). Each run appends the portfolio's latest
realized daily return + today's target weights to a forward log, then reports the
running forward NAV + live Sharpe. No capital — paper only.

Run daily after the US close. Reads/writes etf-trend-paper.jsonl.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

LOG = Path(__file__).resolve().parent / "etf-trend-paper.jsonl"


def _load_ohlc(universe):
    import yfinance as yf
    out = {}
    for s in universe:
        df = yf.Ticker(s).history(period="max", interval="1d")
        if len(df) > 260:
            out[s] = df[["Open", "High", "Low", "Close"]]
    return out


def snapshot() -> dict:
    from portfolio_trend import DEFAULT_UNIVERSE, build_portfolio, current_targets
    ohlc = _load_ohlc(DEFAULT_UNIVERSE)
    res = build_portfolio(ohlc)
    last_date = res.daily_returns.index[-1]
    return {
        "date": last_date.date().isoformat(),
        "day_return": round(float(res.daily_returns.iloc[-1]), 6),
        "targets": current_targets(ohlc),
        "backtest": {k: res.metrics[k] for k in ("cagr_pct", "vol_pct", "sharpe", "max_dd_pct")},
    }


def append_and_summarize() -> dict:
    snap = snapshot()
    logged = []
    if LOG.exists():
        logged = [json.loads(l) for l in LOG.read_text().splitlines() if l.strip()]
    seen = {r["date"] for r in logged}
    if snap["date"] not in seen:
        with LOG.open("a") as f:
            f.write(json.dumps(snap) + "\n")
        logged.append(snap)

    # Forward-only stats from the logged daily returns.
    rs = [r["day_return"] for r in logged]
    n = len(rs)
    nav = 1.0
    for r in rs:
        nav *= (1 + r)
    fwd = {"days": n, "nav": round(nav, 4), "cum_return_pct": round((nav - 1) * 100, 2)}
    if n >= 20:
        mean = sum(rs) / n
        sd = math.sqrt(sum((x - mean) ** 2 for x in rs) / (n - 1))
        fwd["live_sharpe"] = round((mean / sd) * math.sqrt(252), 2) if sd else 0.0
        fwd["live_ann_return_pct"] = round(((nav ** (252 / n)) - 1) * 100, 2)
    else:
        fwd["live_sharpe"] = None
        fwd["note"] = "need ~20 trading days for a live Sharpe"
    return {"today": snap, "forward": fwd}


if __name__ == "__main__":
    import sys
    out = append_and_summarize()
    json.dump(out, sys.stdout, indent=2)
    print()
