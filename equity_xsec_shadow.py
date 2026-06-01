"""Forward PAPER lane for the canonical 12-1 long-only cross-sectional momentum
edge on liquid US large-caps (the factor that externally replicated). No capital.

Monthly cadence, safe to call daily (rolls only when >=28d elapsed). Each roll:
marks the prior month's top-decile book as EXCESS over the equal-weight universe
(survivorship-robust, the metric we trust), net of fee; then forms the new book
from the latest 12-1 momentum ranking. Builds a forward track record -> HAC t.
Fund only if the forward t clears ~2 (hard rule #1).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from equity_xsec_momentum import fetch_panel, FEE
from mexc_trend_hunt import hac_t

LOG = Path(__file__).resolve().parent / "trade-learnings" / "shadow" / "equity-xsec-shadow.jsonl"
LOOKBACK, SKIP, FRAC = 252, 21, 0.10
ROLL_DAYS = 28


def latest_book():
    """(iso_date, [long syms], {sym: price for all eligible}) by 12-1 momentum."""
    dates, by, syms = fetch_panel(years=2)  # 2y is enough for 252d formation
    n = len(dates)
    last, sig_end, form_start = n - 1, n - 1 - SKIP, n - 1 - LOOKBACK
    elig = []
    for s in syms:
        c = by[s]
        if last in c and sig_end in c and form_start in c and c[form_start] > 0:
            elig.append((s, c[sig_end] / c[form_start] - 1, c[last]))
    elig.sort(key=lambda x: x[1])
    k = max(1, int(len(elig) * FRAC))
    longs = [s for s, _, _ in elig[-k:]]
    prices = {s: p for s, _, p in elig}
    return str(dates[last].date()), longs, prices


def mark(prev, px_now):
    longs = prev["longs"]
    long_ret = sum(px_now[s] / prev["prices"][s] - 1 for s in longs if s in px_now) / max(len(longs), 1)
    elig = [s for s in prev["prices"] if s in px_now and prev["prices"][s] > 0]
    mkt = sum(px_now[s] / prev["prices"][s] - 1 for s in elig) / max(len(elig), 1)
    excess = (long_ret - mkt) - FRAC * 2 * FEE  # rough turnover cost
    return {"opened": prev["date"], "long_ret": round(long_ret, 5),
            "mkt_ret": round(mkt, 5), "excess_net": round(excess, 5)}


def report():
    if not LOG.exists():
        print("no equity-xsec shadow log yet")
        return
    marks = [json.loads(l)["mark"]["excess_net"] for l in LOG.read_text().splitlines()
             if l.strip() and json.loads(l).get("mark")]
    if len(marks) < 2:
        print(f"{len(marks)} realised month(s) — need more for a forward t-stat")
        return
    m = sum(marks) / len(marks)
    print(f"realised months={len(marks)} mean_excess={m*100:+.3f}%/mo total={sum(marks)*100:+.2f}% "
          f"forward HAC t={hac_t(marks):+.2f}")


def main():
    import sys
    if "--report" in sys.argv:
        report()
        return
    LOG.parent.mkdir(parents=True, exist_ok=True)
    date, longs, prices = latest_book()
    mark_block = None
    if LOG.exists():
        lines = [l for l in LOG.read_text().splitlines() if l.strip()]
        if lines:
            prev = json.loads(lines[-1])
            from datetime import date as _d
            d0 = _d.fromisoformat(prev["date"])
            d1 = _d.fromisoformat(date)
            if (d1 - d0).days < ROLL_DAYS:
                print(f"not due ({(d1-d0).days}d < {ROLL_DAYS}d) — no roll")
                return
            mark_block = mark(prev, prices)
    LOG.open("a").write(json.dumps({"date": date, "longs": longs, "prices": prices,
                                    "mark": mark_block}) + "\n")
    print(f"logged 12-1 momentum book @ {date}: {len(longs)} longs")
    if mark_block:
        print(f"marked prior ({mark_block['opened']}): excess_net={mark_block['excess_net']*100:+.3f}%")
    print(f"  longs: {', '.join(sorted(longs)[:12])}{' ...' if len(longs)>12 else ''}")


if __name__ == "__main__":
    main()
