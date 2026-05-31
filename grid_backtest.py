"""Fee-accurate spot grid backtester — honest, no-lookahead, OOS + HAC t.

Tests the question the playbook hasn't closed: does a MAKER-ONLY spot grid
survive crypto fees anywhere? A grid ladders limit buys/sells across a range and
profits from oscillation — i.e. it is the highest-turnover form of mean-reversion,
and the playbook says both mean-rev (HAC t≈−2.8) and turnover-fees are what the
crypto fee wall kills. This script is the adversarial check on that prior.

Model (deliberately conservative + lookahead-free):
- The grid range for each window is the [min,max] of the PRIOR window's closes
  (adaptive to recent vol; uses only past data — no lookahead).
- N linearly-spaced levels. One lot per level, equal CASH per level (C/N).
- Per bar, using the bar's own high/low as the fill test (a resting limit at P
  fills iff the bar traded through P):
    * buy a lot at level i if price dips to level i and the lot isn't held;
    * sell a held lot at the next level up if price rises to it.
  A lot bought THIS bar cannot also sell this bar (no same-bar round trips).
- Inventory is marked to the bar close every bar → equity includes the unrealized
  "bag", so a grid that books round-trips while accumulating a losing bag does
  NOT look profitable. At each window end the bag is liquidated at the close.
- Fees charged on every fill (maker and taker scenarios run side by side).

Significance: each window's net return is one sample; the window-return series
goes through stats.significance (Newey-West t + bootstrap p). Buy&hold over the
same span is reported alongside so the "miss the trend" opportunity cost is
visible. Nothing is fundable unless it clears the playbook bar OOS.

Usage:
  python grid_backtest.py                       # full 1095d/Min60 catalog
  python grid_backtest.py --symbols SOL,XRP,BTC --levels 20 --window-bars 720
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path

import numpy as np

from stats import significance

FIXTURE_DIR = Path("/root/apps/ict-autopilot/tests/fixtures")
START_CAPITAL = 1000.0


def load_bars(stem: str) -> list[dict]:
    with open(FIXTURE_DIR / f"{stem}.json") as fh:
        return json.load(fh)


def simulate_grid(bars: list[dict], step: float, max_lots: int, fee: float,
                  sample_bars: int = 24) -> dict:
    """Pure continuous geometric step-grid sim. Returns total_return + equity curve.

    Buy lines sit at p0*(1+step)^n below market; each filled lot rests a sell one
    step up. Lots are CARRIED (the bag) and marked to close every bar; only the
    final bar liquidates. The standard spot-grid product, given its best fair shot
    (no monthly liquidation artifact). Uses only past/current bar data — no lookahead."""
    import math
    p0 = bars[0]["c"]
    r = 1.0 + step
    logr = math.log(r)

    def price(n: int) -> float:
        return p0 * (r ** n)

    def lvl(p: float) -> int:
        return math.floor(math.log(p / p0) / logr)

    held: dict[int, float] = {}          # level index -> qty
    cash = START_CAPITAL
    cash_per_lot = START_CAPITAL / max_lots
    prev_close = p0

    curve = [{"equity": START_CAPITAL}]
    for idx, bar in enumerate(bars):
        bl, bh, bc = bar["l"], bar["h"], bar["c"]
        n_max = math.floor(math.log(bh / p0) / logr)     # highest level price within the bar
        ref = lvl(prev_close)                            # market reference (buys must rest below)

        # Sells: a held lot at n targets price(n+1); fills if the bar reached it.
        for n in sorted(held):
            if n + 1 <= n_max:
                cash += held[n] * price(n + 1) * (1.0 - fee)
                del held[n]
        # Buys: empty levels below market that the bar dipped to, deepest-first,
        # bounded by cash / max_lots.
        n_min = math.ceil(math.log(bl / p0) / logr)
        for n in range(ref, n_min - 1, -1):
            if len(held) >= max_lots or cash < cash_per_lot:
                break
            if n not in held:
                lot_px = price(n)
                qty = cash_per_lot / lot_px
                cash -= cash_per_lot * (1.0 + fee)
                held[n] = qty
        prev_close = bc

        if idx % sample_bars == 0 or idx == len(bars) - 1:
            equity = cash + sum(q * bc for q in held.values())
            curve.append({"equity": equity})

    # Final liquidation of the carried bag.
    final_c = bars[-1]["c"]
    cash += sum(q * final_c * (1.0 - fee) for q in held.values())
    return {"total_return": cash / START_CAPITAL - 1.0, "curve": curve}


def run_symbol(stem: str, step: float, max_lots: int, fee: float,
               sample_bars: int = 24) -> dict | None:
    bars = load_bars(stem)
    if len(bars) < sample_bars * 30:
        return None
    p0 = bars[0]["c"]
    sim = simulate_grid(bars, step, max_lots, fee, sample_bars)
    curve = sim["curve"]
    total_return = sim["total_return"]
    if len(curve) < 8:
        return None
    sig = significance(curve)
    split = int(len(curve) * 0.7)
    oos_sig = significance(curve[split:]) if len(curve) - split >= 2 else {"tstat": 0.0}

    bh_return = bars[-1]["c"] / p0 - 1.0
    eq = np.array([p["equity"] for p in curve])
    dd = float((eq / np.maximum.accumulate(eq) - 1.0).min())

    return {
        "symbol": stem.split("-")[0],
        "windows": len(curve),
        "total_return": total_return,
        "bh_return": bh_return,
        "win_mean": sig["mean_return"],
        "tstat": sig["tstat"],
        "pvalue": sig["pvalue"],
        "oos_t": oos_sig["tstat"],
        "oos_mean": oos_sig.get("mean_return", 0.0),
        "maxdd": dd,
        "significant": sig["significant"],
    }


def _print_table(title: str, rows: list[dict]) -> None:
    print(f"\n{title}")
    print(f"{'sym':<6}{'win':>4}{'totRet':>9}{'b&h':>9}{'winMean':>9}"
          f"{'t':>7}{'p':>8}{'oosT':>7}{'maxDD':>8}  verdict")
    print("-" * 82)
    for r in sorted(rows, key=lambda x: x["tstat"], reverse=True):
        verdict = "REAL+OOS" if (r["significant"] and r["oos_t"] >= 2.0) else \
                  "sig-IS"   if r["significant"] else "dead"
        print(f"{r['symbol']:<6}{r['windows']:>4}{r['total_return']*100:>8.1f}%"
              f"{r['bh_return']*100:>8.1f}%{r['win_mean']*100:>8.2f}%"
              f"{r['tstat']:>7.2f}{r['pvalue']:>8.3f}{r['oos_t']:>7.2f}"
              f"{r['maxdd']*100:>7.1f}%  {verdict}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="Min60")
    ap.add_argument("--days", default="1095")
    ap.add_argument("--symbols", default="", help="comma list of bases, else whole catalog")
    ap.add_argument("--step", type=float, default=0.015, help="geometric grid step (0.015=1.5%)")
    ap.add_argument("--max-lots", type=int, default=30, help="cash cap (covers ~-(1-1/r^N) drawdown)")
    ap.add_argument("--maker-bps", type=float, default=0.0)
    ap.add_argument("--taker-bps", type=float, default=7.5)
    args = ap.parse_args()

    if args.symbols:
        stems = [f"{s.strip().upper()}-{args.days}d-{args.interval}" for s in args.symbols.split(",")]
        stems = [s for s in stems if (FIXTURE_DIR / f"{s}.json").exists()]
    else:
        pat = str(FIXTURE_DIR / f"*-{args.days}d-{args.interval}.json")
        stems = sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(pat))

    print(f"Grid backtest (continuous geometric) · {len(stems)} symbols · step={args.step*100:.2f}% "
          f"· max_lots={args.max_lots} · maker={args.maker_bps}bps vs taker={args.taker_bps}bps")
    print("Bag carried + marked to close every bar; only final bar liquidates. No lookahead.")

    for label, bps in (("MAKER", args.maker_bps), ("TAKER", args.taker_bps)):
        fee = bps / 10000.0
        rows = []
        for stem in stems:
            try:
                r = run_symbol(stem, args.step, args.max_lots, fee)
                if r:
                    rows.append(r)
            except Exception as e:  # noqa: BLE001 — one bad fixture shouldn't kill the sweep
                print(f"  ! {stem}: {e}")
        _print_table(f"=== {label} fees ({bps}bps/fill) ===", rows)
        wins = [r for r in rows if r["significant"] and r["oos_t"] >= 2.0]
        print(f"  → {len(wins)}/{len(rows)} clear REAL+OOS (|t|>=2, p<0.05, OOS t>=2)")


if __name__ == "__main__":
    main()
