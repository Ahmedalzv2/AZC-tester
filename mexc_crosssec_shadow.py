"""Forward shadow lane for the cross-sectional momentum book (PAPER, no capital).

The backtest says cross-sectional 14d momentum (long top decile / short bottom
decile, weekly, market-neutral) is the first crypto structure that survives fees
(Sharpe ~1.0, t~2.4 net of 7.5bp) BUT it's unproven OOS. Hard rule #1: earn the
edge FORWARD before any capital. This lane does exactly that.

Each run (intended weekly via cron):
  1. refresh the universe daily cache from MEXC,
  2. MARK the previously-logged open book — compute its realised market-neutral
     return since it was opened, net of taker turnover,
  3. OPEN the new 14d-momentum decile book and log it.

A growing list of realised weekly returns -> a forward HAC t-stat (see --report).
Config is LOCKED (no tuning) so the forward test is honest. No money moves.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from mexc_trend_hunt import DATA, hac_t, load

LOG = Path(__file__).resolve().parent / "trade-learnings" / "shadow" / "mexc-crosssec-shadow.jsonl"
LOOKBACK = 14      # locked
HOLD = 7           # locked weekly hold; the lane rolls only every HOLD days
FRAC = 0.10        # top/bottom decile, locked
LIQ_TOP = 100      # rank within the 100 most-liquid perps — tradeable AND stronger
                   # (full t 2.39 on all-412 -> 3.73 on top-100; edge is NOT in microcaps)
FEE = 0.00075      # taker per leg


def latest_book():
    """(date, {sym: signed weight}, {sym: close}) for the current decile book,
    formed within the LIQ_TOP most-liquid perps by median daily quote volume."""
    man = json.loads((DATA / "_manifest.json").read_text())
    man.sort(key=lambda m: -m.get("med_qvol", 0))
    syms = [m["symbol"] for m in man[:LIQ_TOP]]
    closes = {}
    last_ts = 0
    for s in syms:
        bars = load(s)
        if len(bars) > LOOKBACK + 1:
            closes[s] = {b.ts: b.c for b in bars}
            last_ts = max(last_ts, bars[-1].ts)
    elig = []
    for s, c in closes.items():
        ts = sorted(c)
        if ts[-1] != last_ts or len(ts) <= LOOKBACK:
            continue
        past = ts[-1 - LOOKBACK]
        if c[past] > 0:
            elig.append((s, c[last_ts] / c[past] - 1.0, c[last_ts]))
    elig.sort(key=lambda x: x[1])
    k = max(1, int(len(elig) * FRAC))
    losers, winners = elig[:k], elig[-k:]
    w = {s: 0.5 / k for s, _, _ in winners}
    w.update({s: -0.5 / k for s, _, _ in losers})
    px = {s: p for s, _, p in winners + losers}
    return last_ts, w, px


def mark(prev, px_now) -> dict:
    """Realised market-neutral return of a previously-opened book, net of fees."""
    gross = 0.0
    covered = 0
    for s, wt in prev["weights"].items():
        if s in px_now and s in prev["prices"] and prev["prices"][s] > 0:
            gross += wt * (px_now[s] / prev["prices"][s] - 1.0)
            covered += 1
    turnover = sum(abs(v) for v in prev["weights"].values())  # full unwind cost
    net = gross - turnover * FEE
    return {"opened": prev["date"], "gross": gross, "net": net,
            "covered": covered, "of": len(prev["weights"])}


def report() -> None:
    if not LOG.exists():
        print("no shadow log yet")
        return
    marks = [json.loads(l)["mark"]["net"] for l in LOG.read_text().splitlines()
             if l.strip() and json.loads(l).get("mark")]
    if len(marks) < 2:
        print(f"{len(marks)} realised period(s) — need more forward data for a t-stat")
        return
    m = sum(marks) / len(marks)
    print(f"realised periods={len(marks)} mean_net={m*100:+.3f}% total={sum(marks)*100:+.2f}% "
          f"forward HAC t={hac_t(marks):+.2f}")


def main() -> None:
    if "--report" in sys.argv:
        report()
        return
    LOG.parent.mkdir(parents=True, exist_ok=True)
    ts, w, px = latest_book()
    # The strategy holds HOLD days. This script is safe to call DAILY: only roll
    # the book (mark prior + open new) once >= HOLD days have elapsed, so a daily
    # cron never corrupts the weekly cadence.
    mark_block = None
    if LOG.exists():
        lines = [l for l in LOG.read_text().splitlines() if l.strip()]
        if lines:
            prev = json.loads(lines[-1])
            elapsed_days = (ts - prev.get("date", 0)) / 86400
            if elapsed_days < HOLD:
                print(f"not due ({elapsed_days:.1f}d < {HOLD}d since last book) — no roll")
                return
            mark_block = mark(prev, px)
    entry = {"date": ts, "lookback": LOOKBACK, "frac": FRAC,
             "weights": w, "prices": px, "mark": mark_block}
    with LOG.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    longs = [s for s, v in w.items() if v > 0]
    shorts = [s for s, v in w.items() if v < 0]
    print(f"logged book @ ts={ts}: {len(longs)} long / {len(shorts)} short")
    if mark_block:
        print(f"marked prior book ({mark_block['opened']}): net={mark_block['net']*100:+.3f}%")
    print(f"  longs:  {', '.join(sorted(longs)[:10])}{' ...' if len(longs)>10 else ''}")
    print(f"  shorts: {', '.join(sorted(shorts)[:10])}{' ...' if len(shorts)>10 else ''}")


if __name__ == "__main__":
    main()
