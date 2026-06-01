"""Honest trend hunt across the full MEXC USDT-perp daily universe.

Answers the question directly: does the proven Donchian trend rule (the one that
scores t=9 as a diversified basket on indices/commodities) earn a fee-surviving
edge on the BROAD crypto universe we never tested — not just the 25 majors?

Method:
  * ONE pre-registered config (prod azc_trend default) run per asset -> clean
    Bonferroni story (N = number of assets), no config p-hacking.
  * Each asset judged at taker 7.5bp AND maker 0bp.
  * The headline test is the DIVERSIFIED BASKET: pool every trade across all
    assets into one netR series (that was the actual edge on indices), HAC t.
  * Per-asset survivors (OOS t>0 and full t past the Bonferroni bar) shortlisted
    for forward shadow — forward time, not in-sample, is what finally proves them.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from mexc_trend_hunt import DATA, Params, backtest, evaluate, hac_t, load

TAKER = 0.00075
MAKER = 0.0


def norm_ppf(p: float) -> float:
    """Acklam inverse-normal — good enough for a significance bar."""
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    pl = 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p <= 1 - pl:
        q = p - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
               (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
           ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)


def main() -> None:
    manifest = json.loads((DATA / "_manifest.json").read_text())
    syms = [m["symbol"] for m in manifest]
    N = len(syms)
    bar_t = norm_ppf(1 - 0.05 / (2 * N))  # two-sided Bonferroni across the universe
    print(f"universe N={N}; Bonferroni bar |t| >= {bar_t:.2f}\n", flush=True)

    p = Params()
    rows = []
    basket_taker: list[float] = []
    basket_maker: list[float] = []
    for s in syms:
        bars = load(s)
        et = evaluate(bars, p, TAKER)
        em = evaluate(bars, p, MAKER)
        if et["n"] == 0:
            continue
        basket_taker.extend(backtest(bars, p, TAKER))
        basket_maker.extend(backtest(bars, p, MAKER))
        rows.append({"sym": s, "n": et["n"],
                     "netR_t": et["netR"], "t_t": et["t"], "oos_t_t": et["oos_t"],
                     "totR_t": et["total_R"],
                     "netR_m": em["netR"], "t_m": em["t"], "oos_t_m": em["oos_t"]})

    rows.sort(key=lambda r: -r["t_t"])

    def basket(rs, label):
        if not rs:
            print(f"{label}: no trades")
            return
        m = sum(rs) / len(rs)
        print(f"{label}: trades={len(rs)} netR/trade={m:+.4f} totalR={sum(rs):+.1f} HAC t={hac_t(rs):+.2f}")

    print("=== DIVERSIFIED BASKET (all assets pooled, prod config) ===")
    basket(basket_taker, "  taker 7.5bp")
    basket(basket_maker, "  maker 0bp  ")

    survivors = [r for r in rows if r["t_t"] >= bar_t and r["oos_t_t"] > 0 and r["netR_t"] > 0]
    print(f"\n=== per-asset survivors (taker, |t|>= {bar_t:.2f} AND OOS t>0): {len(survivors)} ===")
    for r in survivors:
        print(f"  {r['sym']:<16} n={r['n']:<4} netR={r['netR_t']:+.3f} t={r['t_t']:+.2f} OOSt={r['oos_t_t']:+.2f}")

    print("\n=== top 15 by full-sample taker t (for context, NOT all survivors) ===")
    for r in rows[:15]:
        flag = "  <-- maker-only" if (r["t_t"] < 1.5 <= r["t_m"]) else ""
        print(f"  {r['sym']:<16} n={r['n']:<4} netR={r['netR_t']:+.3f} t={r['t_t']:+.2f} "
              f"OOSt={r['oos_t_t']:+.2f} | maker t={r['t_m']:+.2f}{flag}")

    pos = sum(1 for r in rows if r["netR_t"] > 0)
    print(f"\nassets net-positive after taker fees: {pos}/{len(rows)} "
          f"({100*pos/max(len(rows),1):.0f}%)")
    Path("mexc_hunt_results.json").write_text(json.dumps(
        {"N": N, "bar_t": bar_t, "rows": rows,
         "basket_taker_t": hac_t(basket_taker), "basket_maker_t": hac_t(basket_maker),
         "basket_taker_netR": (sum(basket_taker)/len(basket_taker)) if basket_taker else 0,
         "basket_maker_netR": (sum(basket_maker)/len(basket_maker)) if basket_maker else 0},
        indent=2))
    print("\nwrote mexc_hunt_results.json")


if __name__ == "__main__":
    main()
