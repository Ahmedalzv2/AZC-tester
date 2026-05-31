"""Pure IBKR micro-futures rebalance planner — weights → integer contracts.

The proven trend edge is a diversified ETF/index portfolio (portfolio_trend).
This lane validates the FUTURES execution path for the liquid, micro-contract-
mappable core of that universe on an IBKR PAPER account. It is deliberately a
SUBSET: EFA/EEM/DBC/TLT have no liquid micro future, so the futures lane can't
replicate the full portfolio — Alpaca keeps trading the complete ETF book. The
two paper lanes are complementary, not redundant.

No network, no ib_async types here — just the arithmetic of turning target
weights into whole-contract buy/sell deltas, so it's fully unit-testable. The
client translates these abstract orders into IB calls.

Futures sizing is NOTIONAL = price * multiplier per contract; contracts are
rounded to integers (you can't hold a fractional future), which at small equity
means the smallest-weighted legs round to zero — a real capital constraint the
NAV log surfaces, not a bug.
"""
from __future__ import annotations

# ETF (portfolio_trend universe) -> micro future. multiplier = $ per 1.0 index/price point.
CONTRACT_MAP: dict[str, dict] = {
    "SPY": {"symbol": "MES", "exchange": "CME",   "multiplier": 5.0},    # Micro E-mini S&P 500
    "QQQ": {"symbol": "MNQ", "exchange": "CME",   "multiplier": 2.0},    # Micro E-mini Nasdaq-100
    "IWM": {"symbol": "M2K", "exchange": "CME",   "multiplier": 5.0},    # Micro E-mini Russell 2000
    "GLD": {"symbol": "MGC", "exchange": "COMEX", "multiplier": 10.0},   # Micro Gold (10 oz)
    "USO": {"symbol": "MCL", "exchange": "NYMEX", "multiplier": 100.0},  # Micro WTI Crude (100 bbl)
    "SLV": {"symbol": "SIL", "exchange": "COMEX", "multiplier": 1000.0}, # Micro Silver (1000 oz)
}
# Universe legs with no liquid micro future — reported as a coverage gap.
UNMAPPABLE = {"EFA", "EEM", "DBC", "TLT"}

DEFAULT_MIN_CONTRACTS = 1  # a trade must move at least one whole contract


def map_targets(targets: dict[str, float]) -> tuple[dict[str, float], list[str]]:
    """Split portfolio target weights into the futures-mappable subset (keyed by
    FUTURE symbol) and the list of unmappable ETF legs. Absolute weights are kept
    (no renormalisation) so the futures book reflects a PARTIAL execution and the
    uncovered weight stays in cash — honest about what this lane does and doesn't
    replicate."""
    mapped: dict[str, float] = {}
    gap: list[str] = []
    for etf, w in targets.items():
        if etf in CONTRACT_MAP:
            mapped[CONTRACT_MAP[etf]["symbol"]] = w
        elif w > 0.0:
            gap.append(etf)
    return mapped, sorted(gap)


def plan_futures_orders(fut_targets: dict[str, float], equity: float,
                        prices: dict[str, float], positions: dict[str, int],
                        min_contracts: int = DEFAULT_MIN_CONTRACTS) -> list[dict]:
    """fut_targets: future symbol -> target weight (fraction of equity, long-only).
    prices: future symbol -> last price (index/price points).
    positions: future symbol -> current signed contract count.
    Returns abstract orders: {symbol, action: buy|sell, contracts}."""
    orders: list[dict] = []
    mult = {m["symbol"]: m["multiplier"] for m in CONTRACT_MAP.values()}
    for sym in sorted(set(fut_targets) | set(positions)):
        weight = fut_targets.get(sym, 0.0)
        held = positions.get(sym, 0)
        px = prices.get(sym, 0.0)
        per_contract = px * mult.get(sym, 0.0)
        if per_contract <= 0.0:
            continue  # no price -> can't size; skip rather than guess
        target_contracts = int(round(weight * equity / per_contract))
        delta = target_contracts - held
        if abs(delta) < min_contracts:
            continue
        orders.append({
            "symbol": sym,
            "action": "buy" if delta > 0 else "sell",
            "contracts": abs(delta),
        })
    return orders


def assert_paper_account(account_id: str) -> None:
    """IBKR paper accounts are prefixed 'DU' (live are 'U'). Refuse to trade if
    the connected account is not a paper account — belt-and-suspenders against a
    live login ever reaching this lane."""
    if not str(account_id).upper().startswith("DU"):
        raise RuntimeError(
            f"refusing to trade: IBKR account {account_id!r} is not a paper 'DU' account")
