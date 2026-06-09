"""E2 — EXECUTABLE FORM (THE FUNDABILITY TEST).

Hypothesis: long-only, top-decile cross-sectional momentum, restricted to the
100 most-liquid MEXC perps, measured as EXCESS over the equal-weight top-100
universe (the only thing actually tradeable: no short, no borrow), is a real
alpha that clears OOS t>=2.

Why excess-vs-EW: a long-only book inherits the whole market's beta. If the
universe rips, every long-only book looks great — that is not alpha, it is just
holding crypto. The fundability question is whether the SELECTION (top decile)
beats simply holding all 100 names equal-weight, period by period. So we measure
book_return - EW_benchmark_return each rebalance and HAC-test that excess.

Discipline (playbook hard rules):
  * signal from closes <= t ; forward hold return realised t -> t+h (NO lookahead)
  * net turnover fees at taker 0.00075 on the LONG rotation only (long-only book)
  * HAC (Newey-West) t on the net excess series ; 70/30 chronological OOS split
  * judge on OOS t, never in-sample ; a positive IS that fails OOS is NOISE
  * Bonferroni-honest: count every distinct config evaluated

Primary config = top-100 long-only excess, look=14 hold=7 frac=0.10.
Secondary = same on the FULL filtered universe, to test the playbook claim that
restricting to the top-100 STRENGTHENS the edge.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from cross_sectional_mexc import build_panel
from mexc_trend_hunt import DATA
from stats import newey_west_tstat, bootstrap_pvalue

FEE = 0.00075  # taker per unit turnover


def top_liquid_syms(n: int) -> list[str]:
    man = json.loads((DATA / "_manifest.json").read_text())
    man = [m for m in man if m.get("med_qvol") is not None]
    man.sort(key=lambda m: m["med_qvol"], reverse=True)
    return [m["symbol"] for m in man[:n]]


def run_longonly_excess(by_sym, syms, dates, *, lookback, hold, frac, fee=FEE):
    """Long-only top-decile book; return NET-of-fee EXCESS-over-EW per period.

    Each rebalance:
      - eligible = assets with data at d_past, d_now, d_fut and c[d_past] > 0
      - rank eligible by past momentum (c_now/c_past - 1)
      - longs = top k (k = max(1, floor(len*frac))), each weight 1/k
      - book forward return = sum_l (1/k) * (c_fut/c_now - 1)
      - benchmark EW return = mean over ALL eligible of (c_fut/c_now - 1)
      - gross excess = book - benchmark
      - turnover fee charged on the LONG weight changes (taker), subtracted from
        the book before computing excess (benchmark is the costless reference)
      - net excess = gross excess - turnover*fee
    """
    rets: list[float] = []
    prev_w: dict[str, float] = {}
    t = lookback
    while t + hold < len(dates):
        d_now, d_past, d_fut = dates[t], dates[t - lookback], dates[t + hold]
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
        # forward realised return of the long book
        book = 0.0
        for s, wt in w.items():
            c = by_sym[s]
            book += wt * (c[d_fut] / c[d_now] - 1.0)
        # equal-weight benchmark over ALL eligible names this period
        bench = sum(by_sym[s][d_fut] / by_sym[s][d_now] - 1.0 for s, _ in elig) / len(elig)
        # turnover on the long rotation (taker). prev_w is also long-only.
        keys = set(w) | set(prev_w)
        turnover = sum(abs(w.get(s, 0.0) - prev_w.get(s, 0.0)) for s in keys)
        net_excess = (book - turnover * fee) - bench
        rets.append(net_excess)
        prev_w = w
        t += hold
    return rets


def summarize(rets, hold, label):
    n = len(rets)
    mean = sum(rets) / n
    sd = (sum((r - mean) ** 2 for r in rets) / n) ** 0.5
    per_yr = 365.0 / hold
    sharpe = (mean / sd * math.sqrt(per_yr)) if sd > 0 else 0.0
    full_t = newey_west_tstat(rets)
    cut = int(n * 0.7)
    oos = rets[cut:]
    oos_t = newey_west_tstat(oos) if len(oos) >= 5 else 0.0
    boot_p = bootstrap_pvalue(rets)
    return {
        "label": label, "periods": n, "mean_excess_pct": mean * 100.0,
        "sharpe_ann": sharpe, "full_hac_t": full_t, "oos_hac_t": oos_t,
        "bootstrap_p": boot_p, "oos_periods": len(oos), "hold": hold,
    }


def fmt(r):
    return (f"{r['label']:<28} periods={r['periods']:>4} "
            f"mean={r['mean_excess_pct']:+.4f}%/wk Sharpe={r['sharpe_ann']:+.2f} "
            f"FULLt={r['full_hac_t']:+.2f} OOSt={r['oos_hac_t']:+.2f} "
            f"(oosN={r['oos_periods']}) bootp={r['bootstrap_p']:.4f}")


def main():
    dates, by_sym_all, all_syms = build_panel()
    top100 = top_liquid_syms(100)
    top100 = [s for s in top100 if s in by_sym_all]
    full = [s for s in all_syms if s in by_sym_all]
    print(f"panel: {len(all_syms)} total assets, {len(dates)} dates")
    print(f"top-100 liquid present: {len(top100)} ; full filtered universe: {len(full)}\n")

    LOOK, HOLD, FRAC = 14, 7, 0.10
    results = {}

    # PRIMARY: top-100 long-only excess
    r_top = run_longonly_excess(by_sym_all, top100, dates, lookback=LOOK, hold=HOLD, frac=FRAC)
    s_top = summarize(r_top, HOLD, "TOP100 long-only excess")
    results["top100"] = s_top
    print(fmt(s_top))

    # SECONDARY: full filtered universe long-only excess (same params)
    r_full = run_longonly_excess(by_sym_all, full, dates, lookback=LOOK, hold=HOLD, frac=FRAC)
    s_full = summarize(r_full, HOLD, "FULL universe long-only excess")
    results["full"] = s_full
    print(fmt(s_full))

    # restrict verdict
    strengthen = s_top["oos_hac_t"] - s_full["oos_hac_t"]
    print(f"\nRestrict-to-top100 effect on OOS HAC t: "
          f"top100={s_top['oos_hac_t']:+.2f} - full={s_full['oos_hac_t']:+.2f} "
          f"= {strengthen:+.2f}  -> "
          f"{'STRENGTHENS' if strengthen > 0 else 'WEAKENS'}")
    print(f"Same on FULL HAC t: top100={s_top['full_hac_t']:+.2f} vs full={s_full['full_hac_t']:+.2f}")

    # Bonferroni honesty: this experiment evaluated 2 distinct configs.
    configs_tested = 2
    print(f"\nconfigs_tested (distinct books evaluated) = {configs_tested}")

    # Verdict on PRIMARY
    net_positive = s_top["mean_excess_pct"] > 0
    survives = s_top["oos_hac_t"] >= 2.0 and net_positive
    marginal = 1.0 <= s_top["oos_hac_t"] < 2.0
    verdict = "survives" if survives else ("marginal" if marginal else "fails")
    print(f"\nPRIMARY verdict: {verdict} "
          f"(OOS t={s_top['oos_hac_t']:+.2f}, net mean excess={s_top['mean_excess_pct']:+.4f}%/wk)")

    out = {"primary": "top100", "configs_tested": configs_tested,
           "results": results, "restrict_effect_oos_t": strengthen,
           "verdict": verdict, "fee_model": "taker 0.00075 on long rotation; benchmark costless EW"}
    Path(__file__).with_name("e2_longonly_liquid_results.json").write_text(json.dumps(out, indent=2))
    print("\nwrote e2_longonly_liquid_results.json")


if __name__ == "__main__":
    main()
