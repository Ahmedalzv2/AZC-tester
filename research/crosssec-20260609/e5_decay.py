"""E5 — 2026: decay or dispersion drought?

The playbook flags 2026 YTD as negative (~-29%) for the cross-sectional momentum
lane. This decides fundability. Two competing explanations:

  (a) DISPERSION DROUGHT — cross-sectional dispersion (the std of the lookback
      cross-section at each rebalance) is abnormally low in 2026, so there is
      simply no spread to harvest. The edge is dormant, not dead; it returns when
      names spread again.
  (b) GENUINE DECAY — dispersion is normal but the edge is gone. Winners no
      longer continue, the structure broke, dormancy will not save it.

For BOTH long-short and long-only top-100 momentum (look=14, hold=7, frac=0.10),
per calendar year 2021..2026 we report mean %/period and HAC t. SEPARATELY, per
year we compute the average cross-sectional dispersion at the rebalances. Then we
correlate edge magnitude vs dispersion and give a number-backed call on 2026.

Discipline: signal from closes <= t, returns realised t->t+h (no lookahead);
turnover fee charged on every weight change at the taker rate. We reuse the
EXACT eligibility/weighting/fee logic from cross_sectional_mexc.run by inlining
it here only to additionally capture (rebalance-year, dispersion) per period.
"""
from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

import numpy as np

from cross_sectional_mexc import build_panel
from stats import newey_west_tstat, bootstrap_pvalue

FEE = 0.00075  # taker rate, same as the lane default (cross_sectional_mexc.main)
LOOKBACK = 14
HOLD = 7
FRAC = 0.10


def year_of(ts: int) -> int:
    return dt.datetime.utcfromtimestamp(ts).year


def run_with_meta(by_sym, syms, dates, *, lookback, hold, frac, direction, fee):
    """Same walk as cross_sectional_mexc.run, but also returns per-period
    (rebalance_year, dispersion) so we can bucket by calendar year.

    direction:
      'momentum'  -> long-short, long winners / short losers (dollar-neutral)
      'long_only' -> long the top `frac` winners only (equal weight, fully long)

    dispersion := population std (across eligible symbols) of the lookback return
    cross-section at that rebalance.  It is the same for both directions (it is a
    property of the universe, not the book), so we compute it on every period.
    """
    rets: list[float] = []
    meta: list[tuple[int, float]] = []  # (year, dispersion)
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

        # dispersion of the full eligible cross-section (population std)
        lr = np.asarray([r for _, r in elig], dtype=float)
        dispersion = float(lr.std())

        if direction == "momentum":
            w = {}
            for s in winners:
                w[s] = 0.5 / k
            for s in losers:
                w[s] = -0.5 / k
        elif direction == "long_only":
            w = {s: 1.0 / k for s in winners}
        else:
            raise ValueError(direction)

        gross = 0.0
        for s, wt in w.items():
            c = by_sym[s]
            gross += wt * (c[d_fut] / c[d_now] - 1.0)
        keys = set(w) | set(prev_w)
        turnover = sum(abs(w.get(s, 0.0) - prev_w.get(s, 0.0)) for s in keys)
        net = gross - turnover * fee

        rets.append(net)
        meta.append((year_of(d_now), dispersion))
        prev_w = w
        t += hold
    return rets, meta


def per_year_table(rets, meta):
    """Bucket period returns + dispersion by rebalance calendar year."""
    years = sorted({y for y, _ in meta})
    rows = []
    for y in years:
        idx = [i for i, (yy, _) in enumerate(meta) if yy == y]
        r = [rets[i] for i in idx]
        disp = [meta[i][1] for i in idx]
        if not r:
            continue
        mean = float(np.mean(r))
        # HAC t per year; lags default (small samples -> ~2-3 lags)
        t = newey_west_tstat(np.asarray(r)) if len(r) >= 5 else float("nan")
        rows.append({
            "year": y,
            "n_rebalances": len(r),
            "edge_mean": mean,            # mean net %/period (fraction)
            "edge_t": t,
            "avg_dispersion": float(np.mean(disp)),
        })
    return rows


def correl(rows):
    """Correlate |edge_mean| vs avg_dispersion and edge_mean vs avg_dispersion."""
    if len(rows) < 3:
        return float("nan"), float("nan")
    disp = np.asarray([r["avg_dispersion"] for r in rows])
    em = np.asarray([r["edge_mean"] for r in rows])
    r_signed = float(np.corrcoef(disp, em)[0, 1])
    r_abs = float(np.corrcoef(disp, np.abs(em))[0, 1])
    return r_signed, r_abs


def main():
    dates, by_sym, syms = build_panel()
    print(f"panel: {len(syms)} assets, {len(dates)} daily dates "
          f"({dt.datetime.utcfromtimestamp(dates[0]).date()} .. "
          f"{dt.datetime.utcfromtimestamp(dates[-1]).date()})")
    print(f"config: look={LOOKBACK} hold={HOLD} frac={FRAC} fee={FEE} (taker)\n")

    out = {"config": {"lookback": LOOKBACK, "hold": HOLD, "frac": FRAC, "fee": FEE},
           "directions": {}}

    for direction, label in (("momentum", "LONG-SHORT momentum"),
                             ("long_only", "LONG-ONLY top winners")):
        rets, meta = run_with_meta(by_sym, syms, dates, lookback=LOOKBACK,
                                   hold=HOLD, frac=FRAC, direction=direction, fee=FEE)
        rows = per_year_table(rets, meta)

        # full-sample + OOS (70/30 chronological)
        full_t = newey_west_tstat(np.asarray(rets))
        full_mean = float(np.mean(rets))
        cut = int(len(rets) * 0.7)
        oos = rets[cut:]
        oos_t = newey_west_tstat(np.asarray(oos)) if len(oos) >= 5 else float("nan")
        oos_mean = float(np.mean(oos)) if oos else float("nan")
        pval = bootstrap_pvalue(np.asarray(rets))

        r_signed, r_abs = correl(rows)

        print(f"=== {label} ===")
        print(f"{'year':>6}{'n_reb':>7}{'edge_mean%':>12}{'edge_t':>9}{'avg_disp%':>12}")
        for r in rows:
            print(f"{r['year']:>6}{r['n_rebalances']:>7}"
                  f"{r['edge_mean']*100:>+11.3f}%{r['edge_t']:>+9.2f}"
                  f"{r['avg_dispersion']*100:>11.2f}%")
        print(f"full-sample: n={len(rets)} mean={full_mean*100:+.3f}%/period "
              f"HAC t={full_t:+.2f} boot p={pval:.4f}")
        print(f"OOS(30%):    n={len(oos)} mean={oos_mean*100:+.3f}%/period "
              f"HAC t={oos_t:+.2f}")
        print(f"corr(avg_dispersion, edge_mean)     = {r_signed:+.3f}")
        print(f"corr(avg_dispersion, |edge_mean|)   = {r_abs:+.3f}\n")

        out["directions"][direction] = {
            "rows": rows,
            "full_t": full_t, "full_mean": full_mean, "boot_p": pval,
            "oos_t": oos_t, "oos_mean": oos_mean, "n": len(rets),
            "corr_disp_edge": r_signed, "corr_disp_absedge": r_abs,
        }

    # --- 2026 verdict logic (use the long-short lane as the canonical edge) ---
    ms = out["directions"]["momentum"]
    rows = ms["rows"]
    by_year = {r["year"]: r for r in rows}
    disp_vals = {r["year"]: r["avg_dispersion"] for r in rows}
    # historical baseline = years with full edge presence, exclude 2026
    hist_years = [y for y in disp_vals if y != 2026]
    hist_disp = np.asarray([disp_vals[y] for y in hist_years])
    hist_disp_mean = float(hist_disp.mean())
    hist_disp_std = float(hist_disp.std())
    d2026 = disp_vals.get(2026, float("nan"))
    disp_z = (d2026 - hist_disp_mean) / hist_disp_std if hist_disp_std > 0 else float("nan")
    disp_ratio = d2026 / hist_disp_mean if hist_disp_mean > 0 else float("nan")

    print("=== 2026 DIAGNOSIS (long-short momentum canonical) ===")
    print(f"2026 avg_dispersion = {d2026*100:.2f}%  | hist mean "
          f"{hist_disp_mean*100:.2f}% (std {hist_disp_std*100:.2f}%)")
    print(f"2026 dispersion z-score vs 2021-2025 = {disp_z:+.2f}  "
          f"(ratio {disp_ratio:.2f}x)")
    e2026 = by_year.get(2026)
    if e2026:
        print(f"2026 edge_mean = {e2026['edge_mean']*100:+.3f}%/period  "
              f"edge_t = {e2026['edge_t']:+.2f}  (n={e2026['n_rebalances']})")

    # Decision rule:
    #   dispersion drought => 2026 dispersion materially BELOW history (z <= -1)
    #   genuine decay      => dispersion ~normal (z > -1) but edge negative/dead
    drought = (not math.isnan(disp_z)) and disp_z <= -1.0
    edge_dead = e2026 is not None and e2026["edge_mean"] <= 0
    if drought and edge_dead:
        verdict = "DISPERSION DROUGHT (edge dormant; dispersion abnormally low)"
    elif (not drought) and edge_dead:
        verdict = "GENUINE DECAY (dispersion normal but edge gone)"
    elif drought and not edge_dead:
        verdict = "low dispersion but edge still positive — neither clean case"
    else:
        verdict = "dispersion normal and edge positive — no 2026 problem"
    print(f"VERDICT: {verdict}")

    out["verdict_2026"] = {
        "avg_dispersion_2026": d2026,
        "hist_disp_mean": hist_disp_mean,
        "hist_disp_std": hist_disp_std,
        "dispersion_z": disp_z,
        "dispersion_ratio": disp_ratio,
        "edge_2026": e2026,
        "verdict": verdict,
    }

    Path(__file__).with_name("e5_decay_results.json").write_text(json.dumps(out, indent=2))
    print("\nwrote e5_decay_results.json")


if __name__ == "__main__":
    main()
