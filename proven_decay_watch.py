"""Monthly decay tripwire for the proven trend portfolio (the §1 edge).

Re-runs the portfolio-genome search and flags if the edge is FADING — prod
falling off the OOS-positive plateau, or the best config's OOS t collapsing.
It is a MONITOR: it never retunes prod (tuning off the moving holdout would be
knob-mining — the exact trap the deflation gate exists to stop). Self-gates to
~monthly; fail-safe (any error logs and exits 0 so a parent cron never dies).

Run: .venv/bin/python proven_decay_watch.py [--force]
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import traceback
from pathlib import Path

STATUS = Path(__file__).resolve().parent / "research" / "proven-decay-watch.jsonl"
ROLL_DAYS = 28


def decay_verdict(report: dict) -> dict:
    """healthy | softening | decayed, from a run_search report. Pure."""
    p = report["prod"]["oos"]
    b = report["best_by_oos"]["oos"]
    p_t, p_sh, b_t = p["hac_t"], p["sharpe_ann"], b["hac_t"]
    if p_sh <= 0 or b_t < 1.0:
        status = "decayed"           # edge structurally gone on the holdout
    elif p_t < 1.5 or b_t < 2.0:
        status = "softening"         # fading toward the soft-patch floor
    else:
        status = "healthy"           # prod on the OOS-positive plateau, best clears t~2
    return {"status": status, "prod_oos_t": p_t, "prod_oos_sharpe": p_sh,
            "best_oos_t": b_t, "dsr": report["deflated"]["dsr"]}


def _due() -> bool:
    if not STATUS.exists():
        return True
    lines = [l for l in STATUS.read_text().splitlines() if l.strip()]
    if not lines:
        return True
    last = dt.date.fromisoformat(json.loads(lines[-1])["date"])
    return (dt.date.today() - last).days >= ROLL_DAYS


def main() -> None:
    try:
        if "--force" not in sys.argv and not _due():
            print("proven-decay: not due (<28d since last run)")
            return
        from proven_portfolio_search import load_universe, run_search, PROD
        # Use the SAME full grid as the search — DSR deflates by trial count, so a
        # smaller grid would inflate it and read as "newly significant". Keeping
        # the grid fixed makes prod/best OOS t AND DSR comparable month-over-month.
        grid = {"don": [50, 75, 100, 150, 200], "trail": [3, 5, 7],
                "vol_target": [0.10, 0.15, 0.20], "vol_lookback": [60]}
        rep = run_search(load_universe(), grid, prod=PROD)
        v = decay_verdict(rep)
        v["date"] = dt.date.today().isoformat()
        v["n_configs"] = rep["n_configs"]
        v["prod_oos_rank"] = rep["prod"]["oos_rank"] if rep["prod"] else None
        STATUS.parent.mkdir(parents=True, exist_ok=True)
        with STATUS.open("a") as f:
            f.write(json.dumps(v) + "\n")
        flag = "" if v["status"] == "healthy" else "  ⚠️ REVIEW"
        print(f"proven-decay: {v['status']} prod_oos_t={v['prod_oos_t']} "
              f"prod_oos_sharpe={v['prod_oos_sharpe']} best_oos_t={v['best_oos_t']} "
              f"dsr={v['dsr']:.3f} prod_rank={v['prod_oos_rank']}/{v['n_configs']}{flag}")
    except Exception as e:  # noqa: BLE001 — never crash a parent cron
        print(f"proven-decay-watch ERROR (fail-safe, exit 0): {e}", file=sys.stderr)
        traceback.print_exc()


if __name__ == "__main__":
    main()
