"""E3 — ROBUSTNESS / OVERFIT TELL.

Hypothesis: a REAL edge is a PLATEAU across neighbouring knobs, not a single
fragile peak. If only the locked cell (look=14, frac=0.10, hold=7) is strong
and every neighbour collapses, the "edge" is an overfit lone peak and should be
distrusted regardless of how good that one cell looks.

We re-use the EXACT E2 executable form (long-only top-100-liquid cross-sectional
momentum, measured as net-of-taker-fee EXCESS over the equal-weight top-100
universe) and sweep:

    lookback in {7, 14, 21, 30}
    frac     in {0.05, 0.10, 0.20}
    hold     in {7, 14}
    => 24 cells.

For each cell: full HAC t, OOS (last 30%) HAC t, mean excess %/period.

HONEST Bonferroni: N = 24 distinct configs evaluated. The two-sided per-test
bar for family-wise 0.05 is the normal quantile at 1 - (0.05/N)/2. Count how
many cells clear that bar on OOS t. A plateau = the locked cell AND its
immediate neighbours are strong; a lone peak = only the locked cell.

Discipline (playbook hard rules):
  * signal from closes <= t ; forward hold return realised t->t+h (NO lookahead)
  * taker fee 0.00075 per unit turnover on the long rotation; benchmark costless EW
  * judge OOS, never in-sample; a cell strong in-sample but dead OOS is NOISE
  * report exact numbers, not adjectives
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from cross_sectional_mexc import build_panel
from mexc_trend_hunt import DATA
from stats import newey_west_tstat, bootstrap_pvalue

# Re-use the identical E2 executable book so the sweep is apples-to-apples.
from e2_longonly_liquid import FEE, top_liquid_syms, run_longonly_excess

LOOKBACKS = (7, 14, 21, 30)
FRACS = (0.05, 0.10, 0.20)
HOLDS = (7, 14)
LOCKED = {"look": 14, "frac": 0.10, "hold": 7}


def norm_ppf(p: float) -> float:
    """Inverse standard-normal CDF (Acklam rational approximation). scipy-free."""
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
        q = p - 0.5
        r = q * q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
               (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
            ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


def summarize(rets, hold):
    n = len(rets)
    if n == 0:
        return None
    mean = sum(rets) / n
    sd = (sum((r - mean) ** 2 for r in rets) / n) ** 0.5
    per_yr = 365.0 / hold
    sharpe = (mean / sd * math.sqrt(per_yr)) if sd > 0 else 0.0
    full_t = newey_west_tstat(rets)
    cut = int(n * 0.7)
    oos = rets[cut:]
    oos_t = newey_west_tstat(oos) if len(oos) >= 5 else 0.0
    return {
        "periods": n, "mean_excess_pct": mean * 100.0, "sharpe_ann": sharpe,
        "full_hac_t": full_t, "oos_hac_t": oos_t, "oos_periods": len(oos),
        "bootstrap_p": bootstrap_pvalue(rets),
    }


def main():
    dates, by_sym_all, all_syms = build_panel()
    top100 = top_liquid_syms(100)
    top100 = [s for s in top100 if s in by_sym_all]
    print(f"panel: {len(all_syms)} total assets, {len(dates)} dates; "
          f"top-100 liquid present: {len(top100)}\n")

    N = len(LOOKBACKS) * len(FRACS) * len(HOLDS)  # 24
    bar = norm_ppf(1 - (0.05 / N) / 2.0)
    print(f"HONEST Bonferroni: N={N} cells; two-sided 0.05/N bar = {bar:.4f}\n")

    hdr = (f"{'look':>5}{'frac':>6}{'hold':>5} | {'periods':>8}{'mean%':>9}"
           f"{'Sharpe':>8}{'FULLt':>8}{'OOSt':>8}{'bootp':>8}  flag")
    print(hdr)
    print("-" * len(hdr))

    grid = []
    locked_cell = None
    for look in LOOKBACKS:
        for frac in FRACS:
            for hold in HOLDS:
                rets = run_longonly_excess(by_sym_all, top100, dates,
                                           lookback=look, hold=hold, frac=frac, fee=FEE)
                s = summarize(rets, hold)
                is_locked = (look == LOCKED["look"] and abs(frac - LOCKED["frac"]) < 1e-9
                             and hold == LOCKED["hold"])
                oos_passes = s["oos_hac_t"] >= bar
                cell = {"look": look, "frac": frac, "hold": hold,
                        "is_locked": is_locked, "oos_passes_bonferroni": oos_passes, **s}
                grid.append(cell)
                if is_locked:
                    locked_cell = cell
                flag = ("LOCKED" if is_locked else "") + (" *OOS>=bar" if oos_passes else "")
                print(f"{look:>5}{frac:>6.2f}{hold:>5} | "
                      f"{s['periods']:>8}{s['mean_excess_pct']:>+8.3f}%"
                      f"{s['sharpe_ann']:>+8.2f}{s['full_hac_t']:>+8.2f}"
                      f"{s['oos_hac_t']:>+8.2f}{s['bootstrap_p']:>8.4f}  {flag}")

    # ---- Plateau analysis ----------------------------------------------------
    n_oos_pass = sum(1 for g in grid if g["oos_passes_bonferroni"])
    n_oos_pos = sum(1 for g in grid if g["oos_hac_t"] > 0)
    n_full2 = sum(1 for g in grid if g["full_hac_t"] >= 2.0)
    n_oos2 = sum(1 for g in grid if g["oos_hac_t"] >= 2.0)

    # Neighbours of the locked cell = differ in exactly one knob by one grid step.
    def is_neighbour(g):
        steps = 0
        if g["look"] != LOCKED["look"]:
            li = LOOKBACKS.index(LOCKED["look"]); gi = LOOKBACKS.index(g["look"])
            if abs(li - gi) != 1:
                return False
            steps += 1
        if abs(g["frac"] - LOCKED["frac"]) > 1e-9:
            fi = FRACS.index(LOCKED["frac"]); gj = FRACS.index(g["frac"])
            if abs(fi - gj) != 1:
                return False
            steps += 1
        if g["hold"] != LOCKED["hold"]:
            hi = HOLDS.index(LOCKED["hold"]); gh = HOLDS.index(g["hold"])
            if abs(hi - gh) != 1:
                return False
            steps += 1
        return steps == 1 and not g["is_locked"]

    neighbours = [g for g in grid if is_neighbour(g)]
    nbr_oos = [g["oos_hac_t"] for g in neighbours]
    nbr_full = [g["full_hac_t"] for g in neighbours]
    nbr_mean_oos = sum(nbr_oos) / len(nbr_oos) if nbr_oos else 0.0
    nbr_min_oos = min(nbr_oos) if nbr_oos else 0.0
    nbr_pos_share = (sum(1 for x in nbr_oos if x > 0) / len(nbr_oos)) if nbr_oos else 0.0

    print("\n--- PLATEAU vs LONE-PEAK ANALYSIS ---")
    print(f"locked cell (look=14 frac=0.10 hold=7): "
          f"FULLt={locked_cell['full_hac_t']:+.2f} OOSt={locked_cell['oos_hac_t']:+.2f} "
          f"mean={locked_cell['mean_excess_pct']:+.3f}%")
    print(f"cells clearing OOS Bonferroni bar ({bar:.3f}): {n_oos_pass}/{N}")
    print(f"cells with OOS t >= 2.0 (loose): {n_oos2}/{N}")
    print(f"cells with OOS t > 0 (right sign): {n_oos_pos}/{N}")
    print(f"cells with FULL t >= 2.0 (in-sample): {n_full2}/{N}")
    print(f"immediate neighbours of locked cell: {len(neighbours)}")
    print(f"  neighbour OOS t: mean={nbr_mean_oos:+.2f} min={nbr_min_oos:+.2f} "
          f"positive-share={nbr_pos_share:.0%}")
    print(f"  neighbour OOS t values: {[round(x,2) for x in nbr_oos]}")
    print(f"  neighbour FULL t values: {[round(x,2) for x in nbr_full]}")

    # Verdict logic:
    #  - If NO cell clears the OOS Bonferroni bar -> the whole family is noise
    #    (so "plateau vs peak" is moot; it is a flat NON-edge, not even a peak).
    #  - If the locked cell is the only strong OOS cell and neighbours collapse
    #    -> LONE PEAK / overfit.
    #  - If the locked cell AND its neighbours are consistently strong/positive
    #    -> PLATEAU.
    locked_strong = locked_cell["oos_hac_t"] >= 2.0
    plateau = (locked_strong and nbr_pos_share >= 0.75 and nbr_mean_oos >= 1.0
               and nbr_min_oos > -1.0)
    if n_oos_pass == 0 and not locked_strong:
        peak_verdict = "FLAT NON-EDGE (no cell clears OOS Bonferroni; locked not even t>=2 OOS)"
    elif plateau:
        peak_verdict = "PLATEAU (locked cell + neighbours consistently strong/positive)"
    else:
        peak_verdict = "LONE PEAK / FRAGILE (locked cell not surrounded by strong neighbours)"
    print(f"\nPLATEAU-vs-PEAK VERDICT: {peak_verdict}")

    # Fundability verdict on the PRIMARY (locked) cell per schema convention.
    net_positive = locked_cell["mean_excess_pct"] > 0
    if locked_cell["oos_hac_t"] >= 2.0 and net_positive:
        verdict = "survives"
    elif 1.0 <= locked_cell["oos_hac_t"] < 2.0:
        verdict = "marginal"
    else:
        verdict = "fails"
    print(f"PRIMARY (locked) fundability verdict: {verdict} "
          f"(OOSt={locked_cell['oos_hac_t']:+.2f}, mean={locked_cell['mean_excess_pct']:+.3f}%)")

    out = {
        "experiment": "E3 robustness / overfit tell",
        "configs_tested": N,
        "bonferroni_two_sided_bar": bar,
        "locked": LOCKED,
        "locked_cell": locked_cell,
        "n_cells_oos_pass_bonferroni": n_oos_pass,
        "n_cells_oos_t_ge_2": n_oos2,
        "n_cells_oos_t_positive": n_oos_pos,
        "n_cells_full_t_ge_2": n_full2,
        "neighbours": neighbours,
        "neighbour_oos_t_mean": nbr_mean_oos,
        "neighbour_oos_t_min": nbr_min_oos,
        "neighbour_oos_positive_share": nbr_pos_share,
        "plateau_verdict": peak_verdict,
        "primary_fundability_verdict": verdict,
        "fee_model": "taker 0.00075 per unit turnover on long rotation; benchmark costless EW",
        "grid": grid,
    }
    Path(__file__).with_name("e3_robustness_results.json").write_text(json.dumps(out, indent=2))
    print("\nwrote e3_robustness_results.json")


if __name__ == "__main__":
    main()
