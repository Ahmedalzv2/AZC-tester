"""Daily Alpaca paper rebalance for the proven ETF trend portfolio.

Pulls the portfolio's target weights (portfolio_trend), reads the live paper
account, plans the rebalance (rebalance.plan_orders), submits it to Alpaca paper
(or dry-runs), and appends a NAV snapshot to execution/alpaca-nav.jsonl — the
genuine, broker-simulated forward track record (the only thing that ever proves
the edge real). No real money: paper endpoint, hard-guarded.

Dry-run is the DEFAULT; pass --live-paper to actually place paper orders.
Run daily after the US close (orders queue to next open if market is shut).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

NAV_LOG = Path(__file__).resolve().parent / "alpaca-nav.jsonl"


def _fetch_targets() -> dict[str, float]:
    import yfinance as yf
    from portfolio_trend import BROAD_UNIVERSE, FORWARD_PARAMS, current_targets
    # Forward-test the better candidate (2026-06-09): broad 23-market universe +
    # the OOS-selected don200/vt0.10 config. Beats the old 10-ETF/don100 prod on
    # OOS Sharpe, t, and drawdown. See portfolio_trend.BROAD_UNIVERSE.
    ohlc = {}
    for s in BROAD_UNIVERSE:
        df = yf.Ticker(s).history(period="max", interval="1d")
        if len(df) > 260:
            ohlc[s] = df[["Open", "High", "Low", "Close"]]
    return current_targets(ohlc, **FORWARD_PARAMS)


def run(dry_run: bool = True, batch_date: str = "") -> dict:
    from execution.alpaca_client import AlpacaPaper
    from execution.rebalance import plan_orders

    targets = _fetch_targets()
    client = AlpacaPaper(dry_run=dry_run)
    equity = client.equity()
    positions = client.positions()
    orders = plan_orders(targets, equity, positions)

    results = []
    for o in orders:
        try:
            results.append(client.submit(o))
        except Exception as err:
            results.append(f"ERR {o['symbol']} {o['action']}: {err}")
    snapshot = {
        "date": batch_date,
        "mode": "dry-run" if dry_run else "live-paper",
        "equity": round(equity, 2),
        "targets": {k: round(v, 4) for k, v in targets.items()},
        "n_orders": len(orders),
    }
    if not dry_run:
        NAV_LOG.parent.mkdir(parents=True, exist_ok=True)
        with NAV_LOG.open("a") as f:
            f.write(json.dumps(snapshot) + "\n")
    snapshot["results"] = results
    return snapshot


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="execution.run_paper",
                                 description="Daily Alpaca paper rebalance of the proven ETF trend portfolio.")
    ap.add_argument("--live-paper", action="store_true",
                    help="actually submit paper orders (default: dry-run, submit nothing)")
    ap.add_argument("--batch-date", default="", help="YYYY-MM-DD stamp (default: today UTC)")
    args = ap.parse_args(argv)

    batch_date = args.batch_date.strip()
    if not batch_date:
        from datetime import datetime, timezone
        batch_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    snap = run(dry_run=not args.live_paper, batch_date=batch_date)
    print(f"[paper:{snap['mode']}] {batch_date}  equity=${snap['equity']:,.2f}  "
          f"{snap['n_orders']} orders")
    for r in snap["results"]:
        print("  " + r)
    if not args.live_paper:
        print("  (dry-run — nothing submitted; pass --live-paper to execute)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
