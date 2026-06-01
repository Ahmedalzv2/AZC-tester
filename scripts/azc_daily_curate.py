"""Daily self-curating loop for the crypto strategy hunt.

Runs every 24h. The job, in order:
  1. FETCH  — refresh the MEXC daily universe (needed to roll the shadow lane).
  2. ROLL   — advance the cross-sectional momentum shadow lane (marks the prior
              book's realised return when >= 7 days elapsed; no-op otherwise).
  3. CURATE — read the forward track record; keep a compact best-summary; if a
              lane has FAILED with enough forward evidence, auto-invalidate it
              into the rejection registry (the durable one-line memory). Drawdowns
              are NOT failures — invalidation needs a real negative forward sample.
  4. PRUNE  — delete bulky REGENERABLE data (universe CSV cache, large temp result
              JSONs) so disk never piles up. Curated memory (registry, shadow log,
              best-summary, playbook) is kept — it's tiny.
  5. DIGEST — write a one-screen digest + best/failed lines for the operator.

What is NEVER deleted: rejected-strategies.jsonl (invalidation memory), the shadow
log (forward track record), best-summary.json, and anything outside this lane's
own regenerable caches. Shared lab runs / Hermes data are untouched.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "bin" / "python")
SHADOW_LOG = ROOT / "trade-learnings" / "shadow" / "mexc-crosssec-shadow.jsonl"
BEST = ROOT / "trade-learnings" / "shadow" / "best-summary.json"
DIGEST = ROOT / "trade-learnings" / "shadow" / "daily-digest.txt"

# auto-invalidation gate (conservative — momentum has real multi-week drawdowns)
MIN_FWD_PERIODS = 12      # ~3 months of weekly marks before we'll judge
FAIL_T = -1.0             # forward HAC t this negative over a real sample = dead

sys.path.insert(0, str(ROOT))


def sh(*args) -> str:
    p = subprocess.run([PY, *args], cwd=ROOT, capture_output=True, text=True, timeout=1800)
    return (p.stdout or "") + (p.stderr or "")


def main() -> None:
    out = []
    # 1. FETCH (refresh the universe cache)
    out.append("[fetch] " + sh("scripts/fetch_mexc_universe.py").strip().splitlines()[-1])
    # 2. ROLL the shadow lanes (each enforces its own cadence inside)
    roll = sh("mexc_crosssec_shadow.py").strip().splitlines()
    out.append("[roll:crypto-xsec] " + (roll[-1] if roll else "(no output)"))
    eroll = sh("equity_xsec_shadow.py").strip().splitlines()
    out.append("[roll:equity-12-1] " + (eroll[-1] if eroll else "(no output)"))

    # 3. CURATE — read forward marks, keep best-summary, auto-invalidate on real failure
    from mexc_trend_hunt import hac_t
    from lanes.registry import register_rejection, signature, is_rejected
    marks, opened_dates = [], []
    if SHADOW_LOG.exists():
        for line in SHADOW_LOG.read_text().splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            if e.get("mark"):
                marks.append(e["mark"]["net"])
            opened_dates.append(e.get("date"))
    fwd_t = hac_t(marks) if len(marks) >= 2 else 0.0
    fwd_mean = (sum(marks) / len(marks)) if marks else 0.0
    status = "accumulating"
    if len(marks) >= MIN_FWD_PERIODS:
        if fwd_t <= FAIL_T:
            sig_params = {"type": "cross_sectional_momentum", "tf": "1d",
                          "universe": "top100_liquid", "lookback": 14, "decile": 0.1}
            already, _ = is_rejected(signature("cross_sectional_momentum", sig_params,
                                               "mexc", "top100-liquid"))
            if not already:
                register_rejection(
                    "cross_sectional_momentum", sig_params, "mexc", "top100-liquid",
                    reason=f"FORWARD test failed: HAC t={fwd_t:.2f} over {len(marks)} weekly "
                           f"marks (mean {fwd_mean*100:+.2f}%/wk). In-sample t=3.73 did NOT "
                           f"hold out-of-sample/forward — in-sample mirage, do not fund.",
                    metrics={"forward_hac_t": round(fwd_t, 2), "forward_periods": len(marks)},
                    date=str(opened_dates[-1] or "")[:10] or "auto")
                status = "INVALIDATED (forward failure -> registry)"
            else:
                status = "already invalidated"
        elif fwd_t >= 2.0:
            status = "FORWARD-PROVEN (t>=2) -> candidate for gallant promotion"
        else:
            status = f"alive, accumulating (forward t={fwd_t:.2f})"

    BEST.write_text(json.dumps({
        "strategy": "cross_sectional_momentum:top100liquid",
        "in_sample": {"hac_t": 3.73, "sharpe": 1.79, "bootstrap_p": "<1e-4"},
        "forward": {"periods": len(marks), "hac_t": round(fwd_t, 2),
                    "mean_pct_per_week": round(fwd_mean * 100, 3)},
        "status": status,
    }, indent=2))
    out.append(f"[curate] crypto-xsec forward periods={len(marks)} t={fwd_t:+.2f} -> {status}")

    # 3b. equity 12-1 lane forward report (separate log; flag PROMOTE-READY at t>=2)
    eq_log = ROOT / "trade-learnings" / "shadow" / "equity-xsec-shadow.jsonl"
    if eq_log.exists():
        eq_marks = [json.loads(l)["mark"]["excess_net"] for l in eq_log.read_text().splitlines()
                    if l.strip() and json.loads(l).get("mark")]
        eq_t = hac_t(eq_marks) if len(eq_marks) >= 2 else 0.0
        eq_flag = "  *** PROMOTE-READY (forward t>=2) -> consider Alpaca paper ***" if eq_t >= 2.0 else ""
        out.append(f"[curate] equity-12-1 forward months={len(eq_marks)} t={eq_t:+.2f}{eq_flag}")
    if fwd_t >= 2.0 and len(marks) >= MIN_FWD_PERIODS:
        out.append("[curate] *** crypto-xsec PROMOTE-READY (forward t>=2) ***")

    # 4. PRUNE bulky regenerable data (kept: registry, shadow log, best-summary)
    pruned = 0
    cache = ROOT / "data_cache" / "mexc"
    if cache.exists():
        for f in cache.glob("*.csv"):
            f.unlink(); pruned += 1
        man = cache / "_manifest.json"
        if man.exists():
            man.unlink(); pruned += 1
    for big in ("mexc_hunt_results.json", "mexc_crosssec_results.json"):
        p = ROOT / big
        if p.exists():
            p.unlink(); pruned += 1
    out.append(f"[prune] removed {pruned} regenerable files (universe cache + temp results)")

    # 5. DIGEST
    digest = "AZC daily curate\n" + "\n".join(out)
    DIGEST.write_text(digest + "\n")
    print(digest)


if __name__ == "__main__":
    main()
