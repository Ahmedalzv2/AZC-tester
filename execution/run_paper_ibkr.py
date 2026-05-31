"""Daily IBKR paper rebalance for the micro-futures core of the proven trend portfolio.

Mirrors run_paper.py (Alpaca/ETF) but routes the mappable core (MES/MNQ/M2K/MGC/
MCL/SIL) to an IBKR PAPER account via ib_async. Validates the FUTURES execution
path — margin, contract roll, integer-contract sizing — that the eventual live
lane (micro-futures, cheaper than ETFs at small capital) would use. EFA/EEM/DBC/
TLT have no micro future and stay an explicit coverage gap (Alpaca holds those).

Dry-run is the DEFAULT; pass --live-paper to actually place paper orders. Run
daily after the US close. NAV/coverage snapshot → execution/ibkr-nav.jsonl.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

NAV_LOG = Path(__file__).resolve().parent / "ibkr-nav.jsonl"


def _fetch_targets() -> dict[str, float]:
    from execution.run_paper import _fetch_targets as fetch  # reuse the ETF target source
    return fetch()


def run(dry_run: bool = True, batch_date: str = "") -> dict:
    from execution.ibkr_client import IbkrPaper
    from execution.ibkr_futures import map_targets, plan_futures_orders

    targets = _fetch_targets()
    fut_targets, gap = map_targets(targets)

    client = IbkrPaper(dry_run=dry_run).connect()
    try:
        equity = client.equity()
        positions = client.positions()
        prices = client.prices(sorted(fut_targets))
        orders = plan_futures_orders(fut_targets, equity, prices, positions)

        results = []
        for o in orders:
            try:
                results.append(client.submit(o))
            except Exception as err:  # noqa: BLE001
                results.append(f"ERR {o['symbol']} {o['action']}: {err}")
    finally:
        client.disconnect()

    snapshot = {
        "date": batch_date,
        "mode": "dry-run" if dry_run else "live-paper",
        "equity": round(equity, 2),
        "fut_targets": {k: round(v, 4) for k, v in fut_targets.items()},
        "coverage_gap": gap,            # ETF legs with no micro future (held only in Alpaca)
        "n_orders": len(orders),
    }
    if not dry_run:
        NAV_LOG.parent.mkdir(parents=True, exist_ok=True)
        with NAV_LOG.open("a") as f:
            f.write(json.dumps(snapshot) + "\n")
    snapshot["results"] = results
    return snapshot


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="execution.run_paper_ibkr",
                                 description="Daily IBKR paper rebalance of the micro-futures core.")
    ap.add_argument("--live-paper", action="store_true",
                    help="actually submit paper orders (default: dry-run, submit nothing)")
    ap.add_argument("--batch-date", default="", help="YYYY-MM-DD stamp (default: today UTC)")
    args = ap.parse_args(argv)

    batch_date = args.batch_date.strip()
    if not batch_date:
        from datetime import datetime, timezone
        batch_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    snap = run(dry_run=not args.live_paper, batch_date=batch_date)
    print(f"[ibkr:{snap['mode']}] {batch_date}  equity=${snap['equity']:,.2f}  "
          f"{snap['n_orders']} orders  gap={snap['coverage_gap']}")
    for r in snap["results"]:
        print("  " + r)
    if not args.live_paper:
        print("  (dry-run — nothing submitted; pass --live-paper to execute)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
