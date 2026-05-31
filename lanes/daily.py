"""Daily lane orchestrator — the self-policing heartbeat.

Each run, for every lane: if already retired (in the rejection registry), skip;
else evaluate against the lifecycle. Fail -> flatten + register (fair
invalidation, no second chances). Pass -> step the lane forward. The perp lane is
self-contained; the grid lane is reconciled here.

Grid P&L caveat: the grid shares ONE Alpaca paper account with the ETF lane, so
its equity can't be cleanly isolated. We track the BTC position's unrealized P&L
as the grid mark — enough to catch the grid's real failure mode (price trends out
of band -> position deeply underwater -> drawdown kill). Documented limitation.

Dry-run by DEFAULT; --live-paper acts (places/cancels/closes real paper orders).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from lanes import registry
from lanes.lifecycle import Track, evaluate

GRID_NAV = Path(__file__).resolve().parent / "grid-nav.jsonl"


def _grid_track(nav_path: Path, alloc_usd: float) -> Track:
    """Build a lifecycle Track from the grid-NAV history (cumulative P&L / alloc)."""
    if not nav_path.exists():
        return Track(0, 0, 0.0, 0.0, 0.0)
    rows = [json.loads(l) for l in nav_path.read_text().splitlines() if l.strip()]
    if not rows:
        return Track(0, 0, 0.0, 0.0, 0.0)
    pnl_frac = [r["pnl"] / alloc_usd for r in rows]  # cumulative P&L as fraction of capital
    peak = pnl_frac[0]
    max_dd = 0.0
    for v in pnl_frac:
        peak = max(peak, v)
        max_dd = min(max_dd, v - peak)
    days = len({r["date"] for r in rows})
    return Track(n_trades=0, days=days, net_r=pnl_frac[-1], hac_t=0.0, max_dd=max_dd)


def _grid(live_paper: bool, date: str) -> str:
    from execution.alpaca_client import AlpacaPaper
    from lanes import run_grid

    rejected, reason = run_grid._registry_guard()
    if rejected:
        return f"grid RETIRED: {reason} — skipping"

    client = AlpacaPaper(dry_run=not live_paper)
    det = client.position_detail(run_grid.SYMBOL)
    # snapshot mark (unrealized P&L proxy) before deciding
    if live_paper:
        GRID_NAV.parent.mkdir(parents=True, exist_ok=True)
        with GRID_NAV.open("a") as f:
            f.write(json.dumps({"date": date, "pnl": det["unrealized_pl"],
                                "mv": det["market_value"], "qty": det["qty"]}) + "\n")

    track = _grid_track(GRID_NAV, run_grid.ALLOC_USD)
    verdict = evaluate(track)
    if verdict["action"] == "invalidate":
        client.cancel_open_orders(run_grid.SYMBOL)
        client.close(run_grid.SYMBOL)
        sig = registry.register_rejection(
            "grid", {"band_pct": run_grid.BAND_PCT, "n": run_grid.N_LEVELS},
            run_grid.VENUE, run_grid.SYMBOL,
            reason=f"grid invalidated: {verdict['reason']}", metrics=verdict["metrics"], date=date)
        return f"grid INVALIDATED ({verdict['reason']}) -> flattened + registered {sig}"

    # healthy -> reconcile the ladder
    center = run_grid._center_price()
    todo, meta = run_grid.plan(center, det["qty"], client.open_limit_orders(run_grid.SYMBOL))
    placed = 0
    for o in todo:
        try:
            client.submit_limit(run_grid.SYMBOL, o["qty"], o["side"], o["price"]); placed += 1
        except Exception:
            pass
    return (f"grid OK (maxDD {track.max_dd:.2%}, {track.days}d) -> "
            f"reconciled {placed}/{len(todo)} missing rungs")


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lanes.daily",
                                 description="Daily self-policing evaluation of all paper lanes.")
    ap.add_argument("--live-paper", action="store_true", help="act (default: dry-run)")
    ap.add_argument("--date", default="")
    args = ap.parse_args(argv)
    date = args.date.strip()
    if not date:
        from datetime import datetime, timezone
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    mode = "live-paper" if args.live_paper else "dry-run"
    print(f"=== lanes daily [{mode}] {date} ===")

    # Perp lane (self-contained: skips if retired, else evaluates + registers).
    from lanes import perp_sim
    perp_sim._main(["--symbol", "BTC", "--date", date])

    # Grid lane.
    print("  " + _grid(args.live_paper, date))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
