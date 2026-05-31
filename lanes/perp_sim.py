"""Futures perp-sim lane — internal simulator, no broker.

Runs the best crypto family (Donchian trend, production config) on perp price
data with BOTH taker fees AND a funding-rate haircut — the cost the spot/ETF
backtests don't carry. Produces a lifecycle Track and applies the fair-
invalidation verdict; if it fails, the config is written to the rejection
registry so no future study re-tests it.

Per the playbook the crypto trend is marginal pre-funding (t≈0.95) and fee-walled;
funding only makes it worse — so the expected, honest outcome here is a recorded
invalidation. That is the self-policing system working, not a failure of it.
"""
from __future__ import annotations

import argparse

import numpy as np

from bracket_signals import SIGNALS, simulate_signal
from evolab import data
from evolab.genome import FIXED_PARAMS
from lanes import registry
from lanes.lifecycle import Track, evaluate
from stats import _default_lags, newey_west_tstat

VENUE = "perp-sim"
SYMBOL = "BTC"
# Production crypto trend config (playbook: Donchian-30, gated erMin=0.35, trail5).
TREND_PARAMS = {"don": 30, "atrN": 14, "atrMult": 3.0, "trail": 5,
                "erMin": 0.35, "regimeN": 20}
PERP_TAKER = {"makerEntry": False, "makerTp": False, "takerRate": 0.00075, "slipBps": 0}
RISK_PCT = 0.01           # 1% account risk per trade (for DD %-conversion)
FUNDING_R_PER_TRADE = 0.10  # est. perp funding carry per trade, in R (conservative)


def _max_dd_fraction(net_rs: np.ndarray, risk_pct: float = RISK_PCT) -> float:
    if net_rs.size == 0:
        return 0.0
    eq = np.cumsum(net_rs)
    peak = np.maximum.accumulate(eq)
    return float((eq - peak).min() * risk_pct)


def simulate_perp(symbol: str = SYMBOL,
                  funding_r_per_trade: float = FUNDING_R_PER_TRADE) -> Track:
    """Trend on perp data, taker + funding applied, as a lifecycle Track."""
    bars = data.load_asset(symbol)
    params = {**TREND_PARAMS, **FIXED_PARAMS.get("donchian_break", {}), **PERP_TAKER}
    trades = simulate_signal(bars, SIGNALS["donchian_break"], params)
    net_rs = np.asarray([t["netR"] for t in trades], dtype=float) - funding_r_per_trade
    days = int((bars[-1].t - bars[0].t) / 86_400_000) if len(bars) > 1 else 0
    hac_t = float(newey_west_tstat(net_rs, lags=_default_lags(net_rs.size))) if net_rs.size >= 2 else 0.0
    return Track(n_trades=int(net_rs.size), days=days,
                 net_r=float(net_rs.mean()) if net_rs.size else 0.0,
                 hac_t=hac_t, max_dd=_max_dd_fraction(net_rs))


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lanes.perp_sim",
                                 description="Evaluate the perp trend lane; dump to registry on failure.")
    ap.add_argument("--symbol", default=SYMBOL)
    ap.add_argument("--date", default="", help="YYYY-MM-DD (default today UTC)")
    args = ap.parse_args(argv)
    date = args.date.strip()
    if not date:
        from datetime import datetime, timezone
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Self-policing: once invalidated, never re-run (that's the whole point).
    sig = registry.signature("trend", {**TREND_PARAMS, "instrument": "perp", "funding": True},
                             VENUE, args.symbol)
    hit, entry = registry.is_rejected(sig)
    if hit:
        print(f"[perp-sim] {args.symbol} already RETIRED ({entry['date']}): {entry['reason']} — skipping")
        return 0

    track = simulate_perp(args.symbol)
    verdict = evaluate(track)
    print(f"[perp-sim] {args.symbol} trend  n={track.n_trades} days={track.days} "
          f"net_r={track.net_r:+.4f} t={track.hac_t:.2f} maxDD={track.max_dd:.2%} "
          f"-> {verdict['action'].upper()}: {verdict['reason']}")
    if verdict["action"] == "invalidate":
        sig = registry.register_rejection(
            "trend", {**TREND_PARAMS, "instrument": "perp", "funding": True},
            VENUE, args.symbol, reason=f"perp trend invalidated: {verdict['reason']}",
            metrics=verdict["metrics"], date=date)
        print(f"  registered rejection {sig}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
