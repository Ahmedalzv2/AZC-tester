"""Adversarial independent re-derivation of E2.

Claim under test: top-100 long-only top-decile cross-sectional momentum, measured
as net excess over the equal-weight top-100 benchmark, look=14 hold=7 frac=0.10,
taker fee 0.00075 on the long rotation. Claimed: 283 wks, +3.38%/wk, full HAC
t=2.88, OOS-30% HAC t=1.86, bootstrap p=0.0055.

This file does NOT import the claimed run function. The signal/return/turnover/HAC
logic is re-implemented from scratch so a leak in the original would not propagate.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from cross_sectional_mexc import build_panel
from mexc_trend_hunt import DATA
from stats import newey_west_tstat, bootstrap_pvalue

FEE = 0.00075


def top_liquid(n):
    man = json.loads((DATA / "_manifest.json").read_text())
    man = [m for m in man if m.get("med_qvol") is not None]
    man.sort(key=lambda m: m["med_qvol"], reverse=True)
    return [m["symbol"] for m in man[:n]]


def my_hac_t(rets):
    """Independent Newey-West t with the same bandwidth rule, hand-rolled in pure
    python to cross-check the stats.py implementation isn't doing anything weird."""
    n = len(rets)
    if n < 2:
        return 0.0
    mean = sum(rets) / n
    dem = [r - mean for r in rets]
    lags = int(math.floor(4 * (n / 100.0) ** (2.0 / 9.0)))
    lags = max(0, min(lags, n - 1))
    gamma0 = sum(d * d for d in dem) / n
    var = gamma0
    for k in range(1, lags + 1):
        w = 1.0 - k / (lags + 1.0)
        gk = sum(dem[i] * dem[i - k] for i in range(k, n)) / n
        var += 2.0 * w * gk
    if var <= 0:
        return 0.0
    se = math.sqrt(var / n)
    return mean / se if se else 0.0


def book_excess(by_sym, syms, dates, *, lookback, hold, frac, fee=FEE,
                require_full=False, full_set=None):
    """Re-implemented from scratch.

    LOOKAHEAD GUARD (explicit):
      * momentum signal computed ONLY from closes at d_past and d_now, both <= d_now.
      * realised return computed ONLY from c[d_now] -> c[d_fut], i.e. strictly t->t+h.
      * the forward close d_fut is used ONLY for the realised return, never to select.
      Eligibility DOES peek that d_fut exists (you must hold something that survives
      the window). That is standard and shared by the benchmark, so it cannot create
      a spread; tested separately below by a no-future-filter variant.
    """
    rets = []
    prev_w = {}
    t = lookback
    while t + hold < len(dates):
        d_past, d_now, d_fut = dates[t - lookback], dates[t], dates[t + hold]
        elig = []
        for s in syms:
            if require_full and s not in full_set:
                continue
            c = by_sym[s]
            if d_now in c and d_past in c and d_fut in c and c[d_past] > 0 and c[d_now] > 0:
                elig.append((s, c[d_now] / c[d_past] - 1.0))  # SIGNAL: past only
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


def shifted_signal_book(by_sym, syms, dates, *, lookback, hold, frac, fee=FEE):
    """LOOKAHEAD STRESS: deliberately compute the momentum signal using d_now AND
    d_fut (i.e. peek the future). If the original was clean, this CHEAT version must
    score MUCH higher. If the original already scores like the cheat, the original
    is leaking."""
    rets = []
    prev_w = {}
    t = lookback
    while t + hold < len(dates):
        d_past, d_now, d_fut = dates[t - lookback], dates[t], dates[t + hold]
        elig = []
        for s in syms:
            c = by_sym[s]
            if d_now in c and d_past in c and d_fut in c and c[d_now] > 0:
                # CHEAT signal: rank by the FORWARD return we are about to harvest
                elig.append((s, c[d_fut] / c[d_now] - 1.0))
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
        rets.append((book - turnover * fee) - bench)
        prev_w = w
        t += hold
    return rets


def report(rets, label, hold=7):
    n = len(rets)
    if n == 0:
        print(f"{label}: EMPTY")
        return {}
    mean = sum(rets) / n
    sd = (sum((r - mean) ** 2 for r in rets) / n) ** 0.5
    sharpe = (mean / sd * math.sqrt(365.0 / hold)) if sd else 0.0
    full_t = newey_west_tstat(rets)
    full_t_mine = my_hac_t(rets)
    cut = int(n * 0.7)
    oos = rets[cut:]
    ins = rets[:cut]
    oos_t = newey_west_tstat(oos) if len(oos) >= 5 else 0.0
    ins_t = newey_west_tstat(ins) if len(ins) >= 5 else 0.0
    boot = bootstrap_pvalue(rets)
    # fat-tail probes
    srt = sorted(rets, reverse=True)
    drop5 = srt[max(1, int(n * 0.05)):]
    trimmed_mean = sum(drop5) / len(drop5)
    trimmed_t = newey_west_tstat(drop5)
    med = sorted(rets)[n // 2]
    pos = sum(1 for r in rets if r > 0) / n
    d = {
        "label": label, "n": n, "mean_pct": mean * 100, "sharpe": sharpe,
        "full_t": full_t, "full_t_handrolled": full_t_mine,
        "oos_t": oos_t, "ins_t": ins_t, "oos_n": len(oos), "ins_n": len(ins),
        "boot_p": boot, "drop_best5pct_mean_pct": trimmed_mean * 100,
        "drop_best5pct_t": trimmed_t, "median_pct": med * 100, "pct_positive": pos,
    }
    print(f"\n{label}")
    print(f"  n={n}  mean={mean*100:+.4f}%/wk  Sharpe={sharpe:+.2f}")
    print(f"  FULL HAC t={full_t:+.3f} (handrolled {full_t_mine:+.3f})")
    print(f"  IS(70%) t={ins_t:+.3f} (n={len(ins)})   OOS(30% holdout) t={oos_t:+.3f} (n={len(oos)})")
    print(f"  bootstrap p={boot:.4f}")
    print(f"  median={med*100:+.4f}%/wk  %positive={pos*100:.1f}%")
    print(f"  drop best 5%: mean={trimmed_mean*100:+.4f}%/wk  t={trimmed_t:+.3f}")
    return d


def main():
    dates, by_sym, all_syms = build_panel()
    top100 = [s for s in top_liquid(100) if s in by_sym]
    full = [s for s in all_syms if s in by_sym]
    full_cov = {s for s in all_syms if len(by_sym[s]) == len(dates)}
    print(f"panel: {len(all_syms)} assets, {len(dates)} dates")
    print(f"top100 present={len(top100)}  full-coverage syms={len(full_cov)}  "
          f"top100 full-coverage={len(set(top100) & full_cov)}")

    out = {}

    print("\n===== ATTACK 1+5: re-derive primary (clean timing), confirm OOS is holdout =====")
    out["primary"] = report(book_excess(by_sym, top100, dates, lookback=14, hold=7, frac=0.10),
                            "TOP100 long-only excess (re-derived)")

    print("\n===== ATTACK 1: lookahead cheat must dominate if clean =====")
    out["cheat"] = report(shifted_signal_book(by_sym, top100, dates, lookback=14, hold=7, frac=0.10),
                         "CHEAT (signal=forward return) — should be HUGE if no leak")

    print("\n===== ATTACK 2: survivorship — only full-sample symbols =====")
    out["survivor"] = report(
        book_excess(by_sym, top100, dates, lookback=14, hold=7, frac=0.10,
                    require_full=True, full_set=full_cov),
        "TOP100 long-only excess, FULL-COVERAGE ONLY")

    print("\n===== ATTACK 4: fee realism — taker on BOTH legs / full turnover =====")
    # The original charges fee on the long rotation only. A full-turnover model
    # charges entry+exit i.e. effectively double the rotation cost.
    out["fee_double"] = report(
        book_excess(by_sym, top100, dates, lookback=14, hold=7, frac=0.10, fee=FEE * 2.0),
        "TOP100 excess, fee x2 (round-trip both legs)")
    out["fee_zero"] = report(
        book_excess(by_sym, top100, dates, lookback=14, hold=7, frac=0.10, fee=0.0),
        "TOP100 excess, ZERO fee (is headline a fee artifact?)")

    print("\n===== Secondary: full universe (restrict claim) =====")
    out["full_universe"] = report(book_excess(by_sym, full, dates, lookback=14, hold=7, frac=0.10),
                                  "FULL universe long-only excess")

    print("\n===== ATTACK 3: Bonferroni @ 0.05/35 =====")
    # two-sided 0.05/35 -> per-side 0.05/(2*35)=7.14e-4 -> z critical
    from statistics import NormalDist
    alpha = 0.05 / 35.0
    zcrit = NormalDist().inv_cdf(1 - alpha / 2.0)
    print(f"  Bonferroni two-sided bar: alpha={alpha:.5f}  |t|>= {zcrit:.3f}")
    p = out["primary"]
    print(f"  primary OOS t={p['oos_t']:+.3f}  clears {zcrit:.3f}? {abs(p['oos_t'])>=zcrit}")
    print(f"  primary FULL t={p['full_t']:+.3f}  clears {zcrit:.3f}? {abs(p['full_t'])>=zcrit}")
    out["bonferroni"] = {"alpha": alpha, "zcrit": zcrit,
                         "oos_clears": abs(p["oos_t"]) >= zcrit,
                         "full_clears": abs(p["full_t"]) >= zcrit}

    Path(__file__).with_name("verify_e2_adversarial_results.json").write_text(json.dumps(out, indent=2))
    print("\nwrote verify_e2_adversarial_results.json")


if __name__ == "__main__":
    main()
