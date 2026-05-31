"""Spot-grid paper lane on Alpaca crypto (BTC/USD), reconciling design.

Each run: read price + position + open orders, compute the desired grid ladder,
place only the missing rungs (idempotent — a filled buy grows the position that
unlocks the next sell on the following run). Dry-run by DEFAULT; --live-paper
places real paper GTC limit orders. Before doing anything it checks the rejection
registry — if this exact grid config was already invalidated, it refuses to run.

Crypto is 24/7, so this works any time (unlike the ETF lane).
"""
from __future__ import annotations

import argparse

SYMBOL = "BTC/USD"
BAND_PCT = 0.06      # ±6% band around current price
N_LEVELS = 11        # rungs across the band
ALLOC_USD = 2_000.0  # total capital the grid works with (paper)
VENUE = "alpaca-paper"


def _center_price() -> float:
    import yfinance as yf
    df = yf.Ticker("BTC-USD").history(period="5d", interval="1d")
    return float(df["Close"].iloc[-1])


def plan(center: float, position_qty: float, open_orders: list[dict]) -> tuple[list[dict], dict]:
    from lanes.grid import grid_levels, desired_ladder, orders_to_place
    levels = grid_levels(center, BAND_PCT, N_LEVELS)
    per_level_usd = ALLOC_USD / N_LEVELS
    per_level_qty = round(per_level_usd / center, 6)
    desired = desired_ladder(levels, center, per_level_qty, position_qty)
    todo = orders_to_place(desired, open_orders)
    meta = {"levels": levels, "per_level_qty": per_level_qty, "n_desired": len(desired)}
    return todo, meta


def _registry_guard() -> tuple[bool, str]:
    from lanes import registry
    sig = registry.signature(
        "grid", {"band_pct": BAND_PCT, "n": N_LEVELS}, VENUE, SYMBOL)
    hit, entry = registry.is_rejected(sig)
    return hit, (entry or {}).get("reason", "")


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lanes.run_grid",
                                 description="Reconciling spot grid on Alpaca paper crypto.")
    ap.add_argument("--live-paper", action="store_true",
                    help="place real paper limit orders (default: dry-run)")
    args = ap.parse_args(argv)

    rejected, reason = _registry_guard()
    if rejected:
        print(f"[grid] REFUSING — this grid config is in the rejection registry: {reason}")
        return 0

    from execution.alpaca_client import AlpacaPaper
    client = AlpacaPaper(dry_run=not args.live_paper)
    center = _center_price()
    position = client.crypto_position(SYMBOL)
    open_orders = client.open_limit_orders(SYMBOL)
    todo, meta = plan(center, position, open_orders)

    mode = "live-paper" if args.live_paper else "dry-run"
    print(f"[grid:{mode}] {SYMBOL} center=${center:,.0f} band±{BAND_PCT:.0%} "
          f"{N_LEVELS} levels | pos={position} open={len(open_orders)} "
          f"-> placing {len(todo)} of {meta['n_desired']} rungs")
    for o in todo:
        try:
            print("  " + client.submit_limit(SYMBOL, o["qty"], o["side"], o["price"]))
        except Exception as err:
            print(f"  ERR {o['side']} @ {o['price']}: {err}")
    if not args.live_paper:
        print("  (dry-run — nothing placed; pass --live-paper to execute)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
