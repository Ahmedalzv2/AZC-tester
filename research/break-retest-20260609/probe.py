"""Honest fundability probe for the `break_retest` continuation signal.

Mechanises the "break and retest with a rejection candle" idea from
https://www.youtube.com/watch?v=WEyJ-zKAEoA — a recent bar closes beyond an
L-bar level, price taps back into that level, and the confirmation bar closes
back through it. Tested on the deep 4h AZC crypto-perp tapes through the SAME
fee-accurate bracket machinery EvoLab uses (all-taker fees, no maker fiction).

Discipline (playbook §hard-rules):
  - PRE-REGISTERED grid (committed in GRID below before seeing any result).
  - Params selected IN-SAMPLE only; each asset's IS winner is judged ONCE
    out-of-sample. No OOS peeking to pick configs.
  - Bonferroni across the asset basket: a survivor must clear the deflated
    critical t (alpha = 0.05 / N_assets), not the naive t >= 2.

Run:  .venv/bin/python research/break-retest-20260609/probe.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bracket_signals import SIGNALS, simulate_signal  # noqa: E402
from evolab import data  # noqa: E402
from evolab.fitness import _critical_t, assess  # noqa: E402

FAMILY = "break_retest"
MIN_IS_TRADES = 40        # need a real IS sample to select on
OOS_FRACTION = data.OOS_FRACTION

# ── PRE-REGISTERED grid (16 configs). Committed before any result is seen. ──
_EXITS = [
    {"rr": 2.0, "trail": 0},     # fixed 2R target
    {"rr": 99, "trail": 3.0},    # chandelier trail (let continuation run)
]
GRID: list[dict] = [
    {"brL": brL, "brW": brW, "brTolAtr": tol, "atrMult": 2.0, "atrN": 14, **exit}
    for brL in (15, 25)
    for brW in (3, 6)
    for tol in (0.5, 1.0)
    for exit in _EXITS
]


def _is_score(is_bars, params) -> tuple[float, int]:
    """IS selection metric: t-stat of per-trade netR (rewards consistency)."""
    rs = np.asarray([t["netR"] for t in simulate_signal(is_bars, SIGNALS[FAMILY], params)], dtype=float)
    if rs.size < MIN_IS_TRADES:
        return float("-inf"), int(rs.size)
    sd = rs.std(ddof=1)
    if sd == 0:
        return float("-inf"), int(rs.size)
    t = float(rs.mean() / sd * np.sqrt(rs.size))
    # only positive-edge configs are eligible for selection
    return (t if rs.mean() > 0 else float("-inf")), int(rs.size)


def main() -> None:
    assets = data.available_assets()
    rows = []
    for asset in assets:
        bars = data.load_asset(asset)
        is_bars, oos_bars = data.split(bars, OOS_FRACTION)
        # IS selection: pick the config with the best IN-SAMPLE t-stat.
        best_cfg, best_t = None, float("-inf")
        for cfg in GRID:
            params = {**cfg, **data.TAKER}
            score, n_is = _is_score(is_bars, params)
            if score > best_t:
                best_t, best_cfg = score, cfg
        if best_cfg is None:
            rows.append({"asset": asset, "skipped": "no positive-edge IS config"})
            continue
        # OOS judgment ONCE on the IS winner (assess hard-codes all-taker fees).
        v = assess(FAMILY, best_cfg, is_bars, oos_bars)
        rows.append({
            "asset": asset, "cfg": best_cfg, "is_t": round(best_t, 2),
            "oos_n": v["oos"]["n"], "oos_meanR": v["oos"]["meanR"],
            "oos_t": v["oos"]["t"], "oos_p": v["oos"]["p"], "verdict": v["verdict"],
        })

    judged = [r for r in rows if "oos_t" in r and r["oos_n"] >= 40]
    n = len(judged)
    alpha = 0.05 / max(n, 1)
    t_crit = _critical_t(alpha)
    survivors = [r for r in judged if r["oos_t"] >= t_crit and r["oos_meanR"] > 0]

    out = {
        "family": FAMILY,
        "fees": "all-taker 0.075%/leg (engine_bracket TAKER)",
        "grid_size": len(GRID),
        "method": "IS-select per asset, OOS-judge once, Bonferroni across basket",
        "n_assets_judged": n,
        "bonferroni_alpha": round(alpha, 5),
        "critical_t": round(t_crit, 2),
        "n_survivors": len(survivors),
        "survivors": survivors,
        "fundable": len(survivors) > 0,
        "per_asset": sorted(rows, key=lambda r: r.get("oos_t", -99), reverse=True),
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
