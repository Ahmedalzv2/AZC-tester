"""E1 — LEG DECOMPOSITION of the cross-sectional momentum edge.

Hypothesis: the cross-sectional momentum edge is carried by the LONG leg
(executable, no borrow), and reversal is its negative twin.

Locked config: look=14, hold=7, frac=0.10 on the full filtered universe.

We decompose the rebalance into three NET (post-fee) period-return series:

  long-only   : hold the `frac` winners, weight 1/k each (a real long book).
  short-only  : hold the `frac` losers as a SHORT book; reported return is the
                book's P&L (short profits when the losers fall), weight 1/k each.
  long-short  : the existing market-neutral run() (weights +-0.5/k, dollar-neutral).

Plus reversal long-short to confirm the negative-twin claim.

Each series is charged turnover fees at the taker rate 0.00075 on every weight
change (entering AND exiting a name costs `|dw|*fee`). Signal uses closes<=t,
return realised t->t+h, no lookahead — identical convention to run().

Discipline: judge on OUT-OF-SAMPLE (last 30% chronological) HAC t, never IS.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from cross_sectional_mexc import build_panel, run
from mexc_trend_hunt import hac_t
from stats import bootstrap_pvalue, newey_west_tstat

FEE = 0.00075          # taker
LOOK, HOLD, FRAC = 14, 7, 0.10
OOS_FRAC = 0.30        # last 30% chronological = out of sample


def leg_series(by_sym, syms, dates, *, lookback, hold, frac, fee, leg):
    """Net period-return series for a single executable leg.

    leg == 'long'  : long the winners, weight 1/k each (long book P&L).
    leg == 'short' : short the losers, weight 1/k each, reported as the SHORT
                     book's P&L (= -sum(w_long * forward_ret)); turnover identical
                     in magnitude to the long book.

    Turnover fee mirrors run(): sum |w_now - w_prev| over the union of names,
    times the taker fee. For a single leg the book is gross-1.0 long (or short),
    so weights sum to 1.0 in absolute terms — fully invested in that leg.
    """
    rets: list[float] = []
    prev_w: dict[str, float] = {}
    t = lookback
    while t + hold < len(dates):
        d_now, d_past, d_fut = dates[t], dates[t - lookback], dates[t + hold]
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
        names = winners if leg == "long" else losers
        sign = 1.0 if leg == "long" else -1.0
        # fully-invested single leg: each name weight 1/k (abs), signed
        w = {s: sign * (1.0 / k) for s in names}
        gross = 0.0
        for s, wt in w.items():
            c = by_sym[s]
            gross += wt * (c[d_fut] / c[d_now] - 1.0)
        keys = set(w) | set(prev_w)
        turnover = sum(abs(w.get(s, 0.0) - prev_w.get(s, 0.0)) for s in keys)
        net = gross - turnover * fee
        rets.append(net)
        prev_w = w
        t += hold
    return rets


def score(name, rets, hold):
    """Full-sample + OOS-30% metrics for a net period-return series."""
    n = len(rets)
    arr = np.asarray(rets, dtype=float)
    mean = float(arr.mean()) if n else 0.0
    sd = float(arr.std(ddof=0)) if n else 0.0
    per_yr = 365.0 / hold
    sharpe = (mean / sd * math.sqrt(per_yr)) if sd > 0 else 0.0
    full_t = hac_t(rets)
    cut = int(n * (1.0 - OOS_FRAC))           # last 30% chronological
    oos = rets[cut:]
    oos_t = hac_t(oos) if len(oos) >= 5 else 0.0
    oos_mean = float(np.mean(oos)) if oos else 0.0
    nw_full = newey_west_tstat(arr)            # cross-check vs hac_t
    pval = bootstrap_pvalue(arr, iterations=2000, seed=0)
    return {
        "name": name,
        "n": n,
        "mean_pct": mean * 100.0,
        "ann_sharpe": sharpe,
        "full_hac_t": full_t,
        "nw_full_t": nw_full,
        "oos_n": len(oos),
        "oos_mean_pct": oos_mean * 100.0,
        "oos_hac_t": oos_t,
        "bootstrap_p": pval,
        "total_net_pct": float(arr.sum()) * 100.0,
    }


def main():
    dates, by_sym, syms = build_panel(min_assets=20)
    print(f"panel: {len(syms)} assets, {len(dates)} daily dates")
    print(f"locked config: look={LOOK} hold={HOLD} frac={FRAC} fee={FEE} (taker)\n")

    long_rets = leg_series(by_sym, syms, dates, lookback=LOOK, hold=HOLD,
                           frac=FRAC, fee=FEE, leg="long")
    short_rets = leg_series(by_sym, syms, dates, lookback=LOOK, hold=HOLD,
                            frac=FRAC, fee=FEE, leg="short")
    ls_mom = run(by_sym, syms, dates, lookback=LOOK, hold=HOLD, frac=FRAC,
                 direction="momentum", fee=FEE)
    ls_rev = run(by_sym, syms, dates, lookback=LOOK, hold=HOLD, frac=FRAC,
                 direction="reversal", fee=FEE)

    results = [
        score("long_only", long_rets, HOLD),
        score("short_only", short_rets, HOLD),
        score("long_short_momentum", ls_mom, HOLD),
        score("long_short_reversal", ls_rev, HOLD),
    ]

    hdr = (f"{'series':>22}{'n':>5}{'mean%':>9}{'annShrp':>9}"
           f"{'fullHACt':>10}{'OOSn':>6}{'OOSmean%':>10}{'OOS_HACt':>10}{'bootP':>8}")
    print(hdr)
    print("-" * len(hdr))
    for r in results:
        print(f"{r['name']:>22}{r['n']:>5}{r['mean_pct']:>+8.3f}%"
              f"{r['ann_sharpe']:>+9.2f}{r['full_hac_t']:>+10.2f}{r['oos_n']:>6}"
              f"{r['oos_mean_pct']:>+9.3f}%{r['oos_hac_t']:>+10.2f}{r['bootstrap_p']:>8.4f}")

    # sanity: reversal LS should be the negative twin of momentum LS
    mom = np.asarray(ls_mom)
    rev = np.asarray(ls_rev)
    m = min(len(mom), len(rev))
    twin_corr = float(np.corrcoef(mom[:m], rev[:m])[0, 1]) if m > 2 else float("nan")
    print(f"\nmomentum-vs-reversal LS corr = {twin_corr:+.4f}  "
          f"(expect ~-1.0 if perfect negative twin)")
    # long + short book check: does long+short ~= the neutral spread direction?
    lo = np.asarray(long_rets)
    sh = np.asarray(short_rets)
    print(f"long_only total net = {lo.sum()*100:+.2f}% | "
          f"short_only total net = {sh.sum()*100:+.2f}% | "
          f"LS_mom total net = {mom.sum()*100:+.2f}%")

    out = {
        "config": {"look": LOOK, "hold": HOLD, "frac": FRAC, "fee": FEE,
                   "oos_frac": OOS_FRAC},
        "panel": {"assets": len(syms), "dates": len(dates)},
        "results": results,
        "mom_rev_corr": twin_corr,
        "configs_tested": len(results),
    }
    Path(__file__).resolve().parent.joinpath("e1_legs_results.json").write_text(
        json.dumps(out, indent=2))
    print("\nwrote e1_legs_results.json")
    return out


if __name__ == "__main__":
    main()
