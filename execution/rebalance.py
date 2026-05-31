"""Pure rebalance planner: target weights + current book -> abstract orders.

No network, no Alpaca types — just the arithmetic of moving a portfolio to its
target weights, so it's fully unit-testable. The Alpaca client translates these
abstract orders into API calls.

Sizing is by NOTIONAL (dollar value), which Alpaca supports directly for
fractional ETF orders — no share-price lookups needed here. A symbol that's held
but dropped from the targets (or weighted to 0) is CLOSED outright rather than
notional-sold, so the position goes flat cleanly.
"""
from __future__ import annotations

DEFAULT_MIN_TRADE_USD = 50.0  # skip dust trades to avoid daily churn/fees


def plan_orders(targets: dict[str, float], equity: float,
                positions: dict[str, float],
                min_trade_usd: float = DEFAULT_MIN_TRADE_USD) -> list[dict]:
    """targets: symbol -> target weight (fraction of equity, long-only).
    positions: symbol -> current market value in USD.
    Returns abstract orders: {symbol, action: buy|sell|close, [notional]}."""
    orders: list[dict] = []
    for sym in sorted(set(targets) | set(positions)):
        weight = targets.get(sym, 0.0)
        current = positions.get(sym, 0.0)
        # Held but no longer wanted -> close the whole position (clean flat).
        if weight <= 0.0 and current > 0.0:
            orders.append({"symbol": sym, "action": "close"})
            continue
        delta = weight * equity - current
        if abs(delta) < min_trade_usd:
            continue
        orders.append({
            "symbol": sym,
            "action": "buy" if delta > 0 else "sell",
            "notional": round(abs(delta), 2),
        })
    return orders
