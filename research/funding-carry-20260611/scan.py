"""Delta-neutral funding-rate carry on MEXC — first-pass honest feasibility scan.

Strategy family: long spot + short perp (1x, fully collateralized), collect the
funding payments shorts receive when funding is positive. No price direction.
The LAST untested fee-survivable family on the accessible venue (registry checked
2026-06-11: only directional perp-trend-with-funding-cost was rejected).

Two measurements per symbol, both at settle granularity (8h, 3/day):
- ALWAYS-IN: hold the hedge the whole sample → annualized gross funding minus a
  single round-trip cost. Upper bound on capacity of the raw carry.
- GATED (causal): in position only while the trailing TRAIL_SETTLES mean funding
  (through t-1) exceeds ENTER_BPS; exit below EXIT_BPS. Costs charged per leg at
  each entry/exit. HAC t on the per-settle net return series.

NOT modeled (honest gaps, must be closed before any lane): entry/exit basis moves,
short-leg margin during pumps, spot availability per pair, funding-rate fee MEXC
takes, withdrawal frictions. This scan answers only: is the raw carry big enough
to bother modeling those?

Run: .venv/bin/python research/funding-carry-20260611/scan.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from stats import newey_west_tstat  # noqa: E402

import numpy as np  # noqa: E402

BASKET = ["BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT",
          "TRX", "ATOM", "NEAR", "APT", "ARB", "OP", "SUI", "INJ", "AAVE", "UNI",
          "ETC", "BCH", "SEI", "TIA", "RUNE"]
SETTLES_PER_YEAR = 3 * 365

# Costs per ROUND TRIP (enter + exit the hedge), as a fraction of notional.
# Perp legs at the live-probed account taker 0.06-0.075% → use 0.075% each.
# Spot legs at MEXC standard 0.05% each. Total 0.25%/cycle.
PERP_TAKER = 0.00075
SPOT_TAKER = 0.0005
ROUND_TRIP_COST = 2 * PERP_TAKER + 2 * SPOT_TAKER

TRAIL_SETTLES = 21          # 7 days of trailing funding to decide
ENTER_BPS = 0.00003         # enter when trailing mean > 0.003%/8h (~3.3%/yr)
EXIT_BPS = 0.0              # exit when trailing mean goes non-positive

OUT = Path(__file__).resolve().parent / "scan-result.json"


def fetch_funding(symbol: str) -> list[tuple[int, float]]:
    """All available (settleTime, fundingRate), oldest first."""
    rows: list[tuple[int, float]] = []
    page = 1
    while True:
        url = (f"https://contract.mexc.com/api/v1/contract/funding_rate/history"
               f"?symbol={symbol}_USDT&page_num={page}&page_size=1000")
        with urllib.request.urlopen(url, timeout=20) as resp:
            data = json.loads(resp.read())
        if not data.get("success"):
            break
        d = data["data"]
        rows += [(r["settleTime"], float(r["fundingRate"])) for r in d["resultList"]]
        if page >= int(d.get("totalPage", 1)):
            break
        page += 1
        time.sleep(0.25)
    rows.sort()
    return rows


def gated_carry(rates: np.ndarray) -> dict:
    """Causal trailing-funding gate; per-settle net returns incl. churn costs."""
    net = np.zeros(len(rates))
    in_pos = False
    cycles = 0
    for i in range(TRAIL_SETTLES, len(rates)):
        trail = rates[i - TRAIL_SETTLES:i].mean()   # info through t-1 only
        if not in_pos and trail > ENTER_BPS:
            in_pos = True
            cycles += 1
            net[i] -= ROUND_TRIP_COST / 2
        elif in_pos and trail <= EXIT_BPS:
            in_pos = False
            net[i] -= ROUND_TRIP_COST / 2
        if in_pos:
            net[i] += rates[i]
    if in_pos:
        net[-1] -= ROUND_TRIP_COST / 2              # mark the open hedge closed
    t = newey_west_tstat(net)
    return {
        "cycles": cycles,
        "ann_net_pct": round(float(net.mean()) * SETTLES_PER_YEAR * 100, 3),
        "hac_t": round(float(t), 2),
        "time_in_pos_pct": round(float((net != 0).mean()) * 100, 1),
    }


def main() -> int:
    results = []
    for sym in BASKET:
        try:
            rows = fetch_funding(sym)
        except Exception as err:
            print(f"  {sym}: FETCH FAIL {err}")
            continue
        if len(rows) < 200:
            print(f"  {sym}: only {len(rows)} settles, skip")
            continue
        rates = np.asarray([r for _, r in rows], dtype=float)
        span_days = (rows[-1][0] - rows[0][0]) / 86_400_000
        always_ann = float(rates.mean()) * SETTLES_PER_YEAR
        res = {
            "symbol": sym,
            "n_settles": len(rates),
            "span_days": round(span_days, 0),
            "pct_positive": round(float((rates > 0).mean()) * 100, 1),
            "always_in_ann_gross_pct": round(always_ann * 100, 3),
            "always_in_hac_t": round(float(newey_west_tstat(rates)), 2),
            "gated": gated_carry(rates),
        }
        results.append(res)
        g = res["gated"]
        print(f"  {sym:6s} n={res['n_settles']:5d} ({res['span_days']:.0f}d)  "
              f"always {res['always_in_ann_gross_pct']:+7.2f}%/yr gross (t={res['always_in_hac_t']:5.2f})  "
              f"gated {g['ann_net_pct']:+7.2f}%/yr net (t={g['hac_t']:5.2f}, "
              f"{g['cycles']} cycles, in-pos {g['time_in_pos_pct']:.0f}%)")
        time.sleep(0.25)

    results.sort(key=lambda r: r["gated"]["ann_net_pct"], reverse=True)
    basket_net = float(np.mean([r["gated"]["ann_net_pct"] for r in results]))
    summary = {
        "scanned": len(results),
        "params": {"round_trip_cost_pct": ROUND_TRIP_COST * 100,
                   "trail_settles": TRAIL_SETTLES, "enter_bps": ENTER_BPS},
        "basket_mean_gated_net_ann_pct": round(basket_net, 3),
        "results": results,
    }
    OUT.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"\nbasket mean gated net: {basket_net:+.2f}%/yr  -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
