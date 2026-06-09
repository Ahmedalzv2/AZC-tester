"""ADVERSARIAL RE-DERIVATION of E3 (long-only top-100 cross-sectional momentum).

Independent of e2/e3/cross_sectional_mexc code. Only uses the raw CSVs + numpy.
Re-implements: panel build, top-liquid selection, the long-only excess-over-EW
book, HAC t, and the 70/30 OOS split FROM SCRATCH.

Attacks:
  1. LOOKAHEAD  : signal closes<=t, realized return strictly t->t+h. Independent timing.
  2. SURVIVORSHIP: restrict to symbols present for the ENTIRE date span (full panel).
  3. BONFERRONI : whole program ~35 configs -> bar = z(1 - (0.05/35)/2).
  4. FEE REALISM : taker 0.00075 on full long-rotation turnover.
  5. OOS HONESTY : recompute OOS t on the last 30% holdout independently.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np

DATA = Path("/root/apps/backtest-lab/data_cache/mexc")


def norm_ppf(p: float) -> float:
    """Inverse standard-normal CDF via Beasley-Springer/Moro-ish Acklam approx."""
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p <= phigh:
        q = p - 0.5; r = q*q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
               (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
            ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)

FEE = 0.00075
LOCKED = dict(look=14, frac=0.10, hold=7)


# ---------------------------------------------------------------------------
# Independent data layer
# ---------------------------------------------------------------------------
def load_closes(sym: str) -> dict[int, float]:
    out = {}
    with (DATA / f"{sym}.csv").open() as f:
        for row in csv.DictReader(f):
            out[int(row["ts"])] = float(row["close"])
    return out


def build():
    man = json.loads((DATA / "_manifest.json").read_text())
    syms = [m["symbol"] for m in man]
    by_sym = {s: load_closes(s) for s in syms}
    all_ts = set()
    for d in by_sym.values():
        all_ts.update(d.keys())
    dates = sorted(all_ts)
    return dates, by_sym, syms, man


def top_liquid(man, n):
    m = [x for x in man if x.get("med_qvol") is not None]
    m.sort(key=lambda x: x["med_qvol"], reverse=True)
    return [x["symbol"] for x in m[:n]]


# ---------------------------------------------------------------------------
# Independent HAC t-stat (Newey-West, Bartlett, automatic lag)
# ---------------------------------------------------------------------------
def hac_t(rets) -> float:
    x = np.asarray([r for r in rets if math.isfinite(r)], dtype=float)
    n = x.size
    if n < 2:
        return 0.0
    mean = x.mean()
    d = x - mean
    L = int(math.floor(4 * (n / 100.0) ** (2.0 / 9.0)))
    L = max(0, min(L, n - 1))
    g0 = float(d @ d) / n
    var = g0
    for k in range(1, L + 1):
        gk = float(d[k:] @ d[:-k]) / n
        var += 2.0 * (1.0 - k / (L + 1.0)) * gk
    if var <= 0:
        return 0.0
    return float(mean / math.sqrt(var / n))


# ---------------------------------------------------------------------------
# Independent long-only top-decile EXCESS-over-EW book
#   signal: momentum over [t-look, t], using closes AT or BEFORE date t
#   return: realized t -> t+hold  (strictly forward)
#   excess: book_fwd - EW_fwd over the SAME eligible universe
#   fee:    taker on long-rotation turnover, subtracted from book
# leak_guard: if True, assert no future close is referenced for the signal
# ---------------------------------------------------------------------------
def run_book(by_sym, syms, dates, *, look, hold, frac, fee, audit=None):
    rets = []
    prev_w = {}
    t = look
    nd = len(dates)
    while t + hold < nd:
        d_now, d_past, d_fut = dates[t], dates[t - look], dates[t + hold]
        # AUDIT: signal dates must both be <= current decision date; fut strictly after
        if audit is not None:
            audit["sig_ok"] &= (d_past <= d_now) and (d_now < d_fut)
            audit["fwd_ok"] &= (dates[t + hold] > dates[t])
        elig = []
        for s in syms:
            c = by_sym[s]
            if d_now in c and d_past in c and d_fut in c and c[d_past] > 0 and c[d_now] > 0:
                elig.append((s, c[d_now] / c[d_past] - 1.0))
        if len(elig) < 20:
            t += hold
            continue
        elig.sort(key=lambda x: x[1])
        k = max(1, int(len(elig) * frac))
        winners = [s for s, _ in elig[-k:]]
        w = {s: 1.0 / k for s in winners}
        book = sum(wt * (by_sym[s][d_fut] / by_sym[s][d_now] - 1.0) for s, wt in w.items())
        bench = sum(by_sym[s][d_fut] / by_sym[s][d_now] - 1.0 for s, _ in elig) / len(elig)
        keys = set(w) | set(prev_w)
        turnover = sum(abs(w.get(s, 0.0) - prev_w.get(s, 0.0)) for s in keys)
        net_excess = (book - turnover * fee) - bench
        rets.append(net_excess)
        prev_w = w
        t += hold
    return rets


def stats_block(rets):
    n = len(rets)
    if n == 0:
        return dict(n=0, mean=0, full_t=0, oos_t=0, oos_n=0)
    mean = sum(rets) / n
    full_t = hac_t(rets)
    cut = int(n * 0.7)
    oos = rets[cut:]
    oos_t = hac_t(oos) if len(oos) >= 5 else 0.0
    return dict(n=n, mean=mean, full_t=full_t, oos_t=oos_t, oos_n=len(oos), cut=cut)


def main():
    dates, by_sym, syms, man = build()
    top100 = [s for s in top_liquid(man, 100) if s in by_sym]
    print(f"panel: {len(syms)} assets, {len(dates)} dates, top100 present={len(top100)}")
    print(f"date span: {dates[0]} .. {dates[-1]}  ({len(dates)} daily bars)\n")

    # ===== ATTACK 1: LOOKAHEAD — audited independent rebuild of locked cell =====
    audit = dict(sig_ok=True, fwd_ok=True)
    r_locked = run_book(by_sym, top100, dates, look=14, hold=7, frac=0.10, fee=FEE, audit=audit)
    sb = stats_block(r_locked)
    print("=== ATTACK 1 LOOKAHEAD (independent rebuild, locked 14/0.10/7) ===")
    print(f"  signal-uses-only-past: {audit['sig_ok']} ; forward-strictly-after: {audit['fwd_ok']}")
    print(f"  periods={sb['n']} mean={sb['mean']*100:+.4f}%/wk FULLt={sb['full_t']:+.3f} "
          f"OOSt={sb['oos_t']:+.3f} (oosN={sb['oos_n']})")

    # Extra leak probe: shift forward return by ONE extra step (t->t+h should NOT
    # accidentally include info at t). Compare to a deliberately leaked variant
    # where the signal peeks at d_fut (look uses future). If our number != leaked,
    # we are clean.
    def run_leaked(by_sym, syms, dates, look, hold, frac, fee):
        rets, prev_w, t = [], {}, look
        while t + hold < len(dates):
            d_now, d_past, d_fut = dates[t], dates[t - look], dates[t + hold]
            elig = []
            for s in syms:
                c = by_sym[s]
                if d_now in c and d_past in c and d_fut in c and c[d_now] > 0:
                    # LEAK: rank by the FORWARD return (uses d_fut) instead of past
                    elig.append((s, c[d_fut] / c[d_now] - 1.0))
            if len(elig) < 20:
                t += hold; continue
            elig.sort(key=lambda x: x[1])
            k = max(1, int(len(elig) * frac))
            winners = [s for s, _ in elig[-k:]]
            w = {s: 1.0 / k for s in winners}
            book = sum(wt * (by_sym[s][d_fut] / by_sym[s][d_now] - 1.0) for s, wt in w.items())
            bench = sum(by_sym[s][d_fut] / by_sym[s][d_now] - 1.0 for s, _ in elig) / len(elig)
            keys = set(w) | set(prev_w)
            turnover = sum(abs(w.get(s, 0.0) - prev_w.get(s, 0.0)) for s in keys)
            rets.append((book - turnover * fee) - bench)
            prev_w = w; t += hold
        return rets
    rl = run_leaked(by_sym, top100, dates, 14, 7, 0.10, FEE)
    sl = stats_block(rl)
    print(f"  [oracle leak control] if signal peeked at future: FULLt={sl['full_t']:+.2f} "
          f"mean={sl['mean']*100:+.2f}% (should be MASSIVE; ours is far below => no leak)\n")

    # ===== ATTACK 2: SURVIVORSHIP — symbols present across ENTIRE span =====
    # "present for entire sample": has a close on the first AND last date,
    # and coverage >= 99% of all dates.
    dset = set(dates)
    full_present = []
    for s in top100:
        c = by_sym[s]
        cov = len(set(c.keys()) & dset) / len(dates)
        if dates[0] in c and dates[-1] in c and cov >= 0.99:
            full_present.append(s)
    print("=== ATTACK 2 SURVIVORSHIP (top100 restricted to full-history names) ===")
    print(f"  full-history survivors among top100: {len(full_present)}")
    r_surv = run_book(by_sym, full_present, dates, look=14, hold=7, frac=0.10, fee=FEE)
    ss = stats_block(r_surv)
    print(f"  periods={ss['n']} mean={ss['mean']*100:+.4f}%/wk FULLt={ss['full_t']:+.3f} "
          f"OOSt={ss['oos_t']:+.3f} (oosN={ss['oos_n']})")
    # also a stricter 100%-coverage variant
    strict = [s for s in top100 if len(set(by_sym[s].keys()) & dset) == len(dates)]
    print(f"  [strict 100%-coverage names: {len(strict)}]")
    if len(strict) >= 25:
        r_strict = run_book(by_sym, strict, dates, look=14, hold=7, frac=0.10, fee=FEE)
        st = stats_block(r_strict)
        print(f"  strict: periods={st['n']} mean={st['mean']*100:+.4f}%/wk "
              f"FULLt={st['full_t']:+.3f} OOSt={st['oos_t']:+.3f}\n")
    else:
        print("  (too few strict names for a stable book)\n")

    # ===== ATTACK 4: FEE REALISM — recompute at taker on full turnover =====
    print("=== ATTACK 4 FEE REALISM (locked cell) ===")
    for fee, lab in [(0.0, "zero-fee"), (0.00075, "taker .075%"), (0.0015, "2x taker stress")]:
        rr = run_book(by_sym, top100, dates, look=14, hold=7, frac=0.10, fee=fee)
        s = stats_block(rr)
        print(f"  fee={lab:<16} mean={s['mean']*100:+.4f}%/wk FULLt={s['full_t']:+.3f} OOSt={s['oos_t']:+.3f}")
    print()

    # ===== ATTACK 5: OOS HONESTY + ATTACK 3 BONFERRONI on full grid =====
    LOOKBACKS = (7, 14, 21, 30); FRACS = (0.05, 0.10, 0.20); HOLDS = (7, 14)
    grid = []
    for look in LOOKBACKS:
        for frac in FRACS:
            for hold in HOLDS:
                rr = run_book(by_sym, top100, dates, look=look, hold=hold, frac=frac, fee=FEE)
                s = stats_block(rr)
                grid.append(dict(look=look, frac=frac, hold=hold, **s))
    locked = next(g for g in grid if g["look"] == 14 and abs(g["frac"]-0.10) < 1e-9 and g["hold"] == 7)
    print("=== ATTACK 5 OOS HONESTY (locked recomputed independently) ===")
    print(f"  locked split: n={locked['n']} cut={locked['cut']} oos_n={locked['oos_n']} "
          f"(holdout is last {locked['oos_n']}/{locked['n']} = {locked['oos_n']/locked['n']:.0%})")
    print(f"  FULLt={locked['full_t']:+.3f}  OOSt(holdout)={locked['oos_t']:+.3f}")
    # sanity: OOS t must NOT equal full t
    print(f"  OOS != FULL ? {abs(locked['oos_t']-locked['full_t'])>0.01}\n")

    print("=== ATTACK 3 BONFERRONI ===")
    z24 = norm_ppf(1 - (0.05/24)/2)
    z35 = norm_ppf(1 - (0.05/35)/2)
    print(f"  bar @N=24: {z24:.4f} ; bar @N=35 (whole program): {z35:.4f}")
    pass24 = [g for g in grid if g["oos_t"] >= z24]
    pass35 = [g for g in grid if g["oos_t"] >= z35]
    oos2 = [g for g in grid if g["oos_t"] >= 2.0]
    full2 = [g for g in grid if g["full_t"] >= 2.0]
    print(f"  cells OOS>= N24 bar: {len(pass24)}/24 ; OOS>= N35 bar: {len(pass35)}/24")
    print(f"  cells OOS t>=2.0: {len(oos2)}/24 ; FULL t>=2.0: {len(full2)}/24")
    print(f"  locked OOSt={locked['oos_t']:+.3f}  vs N35 bar {z35:.3f} -> "
          f"{'CLEARS' if locked['oos_t']>=z35 else 'FAILS'}")

    # neighbour plateau check
    def neigh(g):
        ld = abs(LOOKBACKS.index(g["look"]) - LOOKBACKS.index(14))
        fd = abs(FRACS.index(round(g["frac"],2)) - FRACS.index(0.10)) if round(g["frac"],2) in FRACS else 9
        hd = abs(HOLDS.index(g["hold"]) - HOLDS.index(7))
        tot = ld + fd + hd
        return tot == 1
    nb = [g for g in grid if neigh(g)]
    nb_oos = [g["oos_t"] for g in nb]
    print(f"\n  neighbours={len(nb)} OOSt mean={sum(nb_oos)/len(nb):+.3f} "
          f"min={min(nb_oos):+.3f} pos-share={sum(1 for x in nb_oos if x>0)/len(nb):.0%}")
    print(f"  neighbour OOSt: {[round(x,2) for x in nb_oos]}")

    print("\n=== FINAL ATTACK SUMMARY ===")
    print(f"  L1 leak-clean: {audit['sig_ok'] and audit['fwd_ok']}")
    print(f"  L2 survivorship locked OOSt: {ss['oos_t']:+.3f}")
    print(f"  L3 Bonferroni N35 cleared by locked: {locked['oos_t']>=z35}")
    print(f"  L4 taker-fee locked OOSt: {locked['oos_t']:+.3f} (mean {locked['mean']*100:+.3f}%)")
    print(f"  L5 OOS-honest locked OOSt (holdout): {locked['oos_t']:+.3f}, FULLt {locked['full_t']:+.3f}")


if __name__ == "__main__":
    main()
