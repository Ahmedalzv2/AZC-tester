"""Pure spot-grid engine: levels, the desired order ladder, and reconciliation.

A grid profits from price oscillating inside a band — buy limits below price,
sell limits above — and bleeds when price trends out of the band (caught by the
lifecycle's drawdown kill). Design is RECONCILING, not event-driven: each run
computes the desired ladder and places only what's missing, so re-running is
idempotent and a filled buy naturally grows the position that lets the next sell
level be placed. Spot constraint honoured: you can only sell what you hold (no
shorting), so sell levels are capped by current holdings.

All pure / no network — the runner supplies live price, position, and open orders.
"""
from __future__ import annotations


def grid_levels(center: float, band_pct: float, n: int) -> list[float]:
    """n price levels evenly spaced across center*(1±band_pct)."""
    lo, hi = center * (1 - band_pct), center * (1 + band_pct)
    step = (hi - lo) / (n - 1)
    return [round(lo + i * step, 2) for i in range(n)]


def desired_ladder(levels: list[float], price: float, per_level_qty: float,
                   position_qty: float = 0.0) -> list[dict]:
    """Buy limits at every level below price; sell limits at levels above price,
    but only as many as current holdings can cover (spot = no shorting), nearest
    sell levels first."""
    ladder = [{"price": lvl, "side": "buy", "qty": per_level_qty}
              for lvl in levels if lvl < price]
    sellable = int(position_qty // per_level_qty) if per_level_qty > 0 else 0
    for lvl in sorted((l for l in levels if l > price))[:sellable]:
        ladder.append({"price": lvl, "side": "sell", "qty": per_level_qty})
    return ladder


def orders_to_place(desired: list[dict], open_orders: list[dict]) -> list[dict]:
    """Desired orders not already resting on the book (matched on side+price)."""
    def key(o: dict) -> tuple:
        return (o["side"], round(float(o["price"]), 2))
    have = {key(o) for o in open_orders}
    return [o for o in desired if key(o) not in have]
