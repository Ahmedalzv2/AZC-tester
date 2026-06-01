"""Cross-sectional long-short market-neutral hunt on the MEXC perp universe.

The one crypto structure never tested here. Instead of betting on direction
per-asset (trend/fade — both dead), each rebalance we RANK the universe by a
signal and go long the top / short the bottom, dollar-neutral. The market move
cancels (neutral); we only harvest the cross-sectional spread. Lower, smarter
turnover than per-asset chasing, so it has the best shot at the fee wall.

Two directions tested:
  momentum : long recent winners, short recent losers  (cross-sectional momentum)
  reversal : long recent losers, short recent winners  (cross-sectional reversal)

Honest discipline: signal from closes <= t, returns realised t->t+h (no lookahead);
turnover fee charged on every weight change at the taker rate; HAC t on the net
period-return series; 70/30 OOS split; small config grid (Bonferroni-light).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from mexc_trend_hunt import DATA, hac_t, load


def build_panel(min_assets: int = 20):
    """Return (dates, closes) where closes[date][sym] exists only if the asset
    traded on that date. Daily timestamps are aligned on the shared calendar."""
    syms = [m["symbol"] for m in json.loads((DATA / "_manifest.json").read_text())]
    by_sym = {}
    all_ts = set()
    for s in syms:
        bars = load(s)
        d = {b.ts: b.c for b in bars}
        by_sym[s] = d
        all_ts.update(d.keys())
    dates = sorted(all_ts)
    return dates, by_sym, syms


def run(by_sym, syms, dates, *, lookback, hold, frac, direction, fee):
    """Walk the calendar in `hold`-day steps; return the net period-return series."""
    rets: list[float] = []
    prev_w: dict[str, float] = {}
    idx = {t: i for i, t in enumerate(dates)}
    t = lookback
    while t + hold < len(dates):
        d_now, d_past, d_fut = dates[t], dates[t - lookback], dates[t + hold]
        # assets with full data across signal window AND the forward hold window
        elig = []
        for s in syms:
            c = by_sym[s]
            if d_now in c and d_past in c and d_fut in c and c[d_past] > 0:
                elig.append((s, c[d_now] / c[d_past] - 1.0))
        if len(elig) < 20:
            t += hold
            continue
        elig.sort(key=lambda x: x[1])
        k = max(1, int(len(elig) * frac))
        losers = [s for s, _ in elig[:k]]
        winners = [s for s, _ in elig[-k:]]
        if direction == "momentum":
            longs, shorts = winners, losers
        else:  # reversal
            longs, shorts = losers, winners
        w = {}
        for s in longs:
            w[s] = 0.5 / k
        for s in shorts:
            w[s] = -0.5 / k
        # forward realised return of the book over the hold window
        gross = 0.0
        for s, wt in w.items():
            c = by_sym[s]
            gross += wt * (c[d_fut] / c[d_now] - 1.0)
        # turnover fee: every change in weight is a trade at taker rate
        keys = set(w) | set(prev_w)
        turnover = sum(abs(w.get(s, 0.0) - prev_w.get(s, 0.0)) for s in keys)
        net = gross - turnover * fee
        rets.append(net)
        prev_w = w
        t += hold
    return rets


def main() -> None:
    dates, by_sym, syms = build_panel()
    print(f"panel: {len(syms)} assets, {len(dates)} daily dates\n")
    fee = 0.00075
    grid = []
    print(f"{'dir':>9}{'look':>5}{'hold':>5}{'frac':>6} | {'periods':>8}{'mean%':>8}{'ann.Sharpe':>11}{'HACt':>7}{'OOSt':>7}")
    for direction in ("momentum", "reversal"):
        for lookback in (7, 14, 30, 60):
            for hold in (7, 14, 30):
                for frac in (0.1, 0.2):
                    rets = run(by_sym, syms, dates, lookback=lookback, hold=hold,
                               frac=frac, direction=direction, fee=fee)
                    if len(rets) < 10:
                        continue
                    mean = sum(rets) / len(rets)
                    sd = (sum((r - mean) ** 2 for r in rets) / len(rets)) ** 0.5
                    per_yr = 365.0 / hold
                    sharpe = (mean / sd * math.sqrt(per_yr)) if sd > 0 else 0.0
                    t = hac_t(rets)
                    cut = int(len(rets) * 0.7)
                    oos = rets[cut:]
                    ot = hac_t(oos) if len(oos) >= 5 else 0.0
                    grid.append({"dir": direction, "look": lookback, "hold": hold,
                                 "frac": frac, "n": len(rets), "mean": mean,
                                 "sharpe": sharpe, "t": t, "oos_t": ot})
                    print(f"{direction:>9}{lookback:>5}{hold:>5}{frac:>6.2f} | "
                          f"{len(rets):>8}{mean*100:>+7.2f}%{sharpe:>+11.2f}{t:>+7.2f}{ot:>+7.2f}")
    N = len(grid)
    bar = 2.807  # ~ two-sided 0.05/24 Bonferroni
    win = [g for g in grid if g["t"] >= bar and g["oos_t"] > 0 and g["mean"] > 0]
    print(f"\nconfigs={N}; Bonferroni-ish bar |t|>= {bar}")
    print(f"survivors (t>=bar AND OOS t>0 AND mean>0): {len(win)}")
    for g in sorted(win, key=lambda x: -x["t"]):
        print(f"  {g['dir']} look={g['look']} hold={g['hold']} frac={g['frac']} "
              f"Sharpe={g['sharpe']:+.2f} t={g['t']:+.2f} OOSt={g['oos_t']:+.2f}")
    Path("mexc_crosssec_results.json").write_text(json.dumps(grid, indent=2))
    print("\nwrote mexc_crosssec_results.json")


if __name__ == "__main__":
    main()
