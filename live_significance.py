"""Live forward-test significance tracker for the AZC shadow lanes.

The backtest t-stat can be overfit; a t-stat built from trades the strategy
took AFTER it was frozen cannot. This reads the shadow lanes' resolved-exit
records (`netR` per trade, written live by azc-trend-shadow / azc-meanrev) and
computes the running Newey-West t-stat + bootstrap p-value — the honest,
un-curve-fittable verdict that accrues over real time.

It also reports cadence (trades/week) and a rough ETA to statistical power, so
the wait for a real answer is visible rather than open-ended.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from stats import _default_lags, bootstrap_pvalue, newey_west_tstat

# Shadow logs live in the AZC repo; the container mounts /root:/root.
SHADOW_DIR = Path("/root/apps/ict-autopilot/trade-learnings/shadow")
LANES = {
    "trend": SHADOW_DIR / "trend-signals.jsonl",
    "meanrev": SHADOW_DIR / "meanrev-signals.jsonl",
}
WEEK_MS = 7 * 24 * 3600 * 1000
# A t-stat over a handful of bar-events is numerically unstable (2 near-equal
# bar sums read t>500); the flag may not fire below this many independent bars.
MIN_INDEPENDENT_BARS = 10


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _cluster_by_bar(exits: list[dict[str, Any]]) -> list[float]:
    """Collapse exits to one portfolio-R observation per 4h bar. Trades that
    resolve on the same bar across a correlated basket are one market event,
    not independent samples — pooling them inflates t (2026-06-10 teardown:
    26 trades / 8 bars read t=3.07 per-trade vs ~1.9 per-bar)."""
    by_bar: dict[float, float] = {}
    for r in exits:
        bar = r.get("barTs") if isinstance(r.get("barTs"), (int, float)) else r.get("ts", 0)
        by_bar[bar] = by_bar.get(bar, 0.0) + float(r["netR"])
    return [by_bar[k] for k in sorted(by_bar)]


def _open_positions(records: list[dict[str, Any]]) -> list[str]:
    """Symbols whose latest decision is an unresolved entry. Counted per
    symbol, not per entry row — crash-restart loops re-log the same entry,
    and the lane holds at most one position per symbol."""
    state: dict[Any, bool] = {}
    for r in records:
        d = r.get("decision")
        if d == "entry":
            state[r.get("symbol")] = True
        elif d == "exit":
            state[r.get("symbol")] = False
    return sorted(s for s, open_ in state.items() if open_ and s is not None)


def _trades_to_significance(net_rs: list[float]) -> dict[str, Any]:
    arr = np.asarray(net_rs, dtype=float)
    n = int(arr.size)
    if n < 2:
        return {"n": n, "mean_netR": round(float(arr.mean()), 4) if n else 0.0,
                "tstat": 0.0, "pvalue": 1.0, "significant": False}
    t = newey_west_tstat(arr, lags=_default_lags(n))
    p = bootstrap_pvalue(arr)
    return {
        "n": n,
        "mean_netR": round(float(arr.mean()), 4),
        "tstat": round(t, 3),
        "pvalue": round(p, 4),
        "significant": bool(abs(t) >= 2.0 and p < 0.05),
    }


def _eta_to_power(net_rs: list[float], trades_per_week: float) -> dict[str, Any]:
    """Rough n needed for |t|=2 at the current effect size, and the ETA at the
    observed cadence. Honest about how long forward proof actually takes."""
    arr = np.asarray(net_rs, dtype=float)
    n = arr.size
    if n < 2:
        return {"n_needed": None, "weeks_eta": None, "note": "need >=2 trades to estimate"}
    mean = arr.mean()
    sd = arr.std(ddof=1)
    if mean <= 0 or sd == 0:
        return {"n_needed": None, "weeks_eta": None, "note": "no positive edge to power yet"}
    n_needed = math.ceil((2.0 * sd / mean) ** 2)
    remaining = max(0, n_needed - n)
    weeks = round(remaining / trades_per_week, 1) if trades_per_week > 0 else None
    return {"n_needed": int(n_needed), "remaining": int(remaining), "weeks_eta": weeks,
            "note": "at current effect size + cadence; effect size will drift as data accrues"}


def lane_significance(path: Path) -> dict[str, Any]:
    records = _read_records(path)
    exits = [r for r in records if r.get("decision") == "exit" and r.get("netR") is not None]
    entries = [r for r in records if r.get("decision") == "entry"]
    skips = [r for r in records if r.get("decision") == "skip"]
    net_rs = [float(r["netR"]) for r in exits]
    ts = [r["ts"] for r in records if isinstance(r.get("ts"), (int, float))]

    span_days = None
    trades_per_week = 0.0
    if len(ts) >= 2 and max(ts) > min(ts):
        span_ms = max(ts) - min(ts)
        span_days = round(span_ms / (24 * 3600 * 1000), 2)
        if len(net_rs) >= 1:
            trades_per_week = round(len(net_rs) / (span_ms / WEEK_MS), 2)

    sig = _trades_to_significance(net_rs)

    # Honest verdict layer: judge on independent bar-events with the open
    # book marked against us, not on pooled per-trade rows. A trail-only
    # design resolves winners fast and parks losers under the wide initial
    # stop, so resolved-only stats carry survivorship bias.
    bar_rs = _cluster_by_bar(exits)
    cluster = _trades_to_significance(bar_rs)
    cluster["n_bars"] = len(bar_rs)
    open_syms = _open_positions(records)
    stress_half = _trades_to_significance(bar_rs + [-0.5] * len(open_syms))
    stress_full = _trades_to_significance(bar_rs + [-1.0] * len(open_syms))
    significant = bool(
        cluster["n_bars"] >= MIN_INDEPENDENT_BARS
        and abs(cluster["tstat"]) >= 2.0 and cluster["pvalue"] < 0.05
        and abs(stress_half["tstat"]) >= 2.0
    )

    wins = sum(1 for r in exits if r.get("win"))
    # Last resolved trades, so a remote supervisor can DIAGNOSE a failing lane
    # (which dir/symbol/exit is bleeding), not just read the aggregate t-stat.
    recent = [
        {"ts": r.get("ts"), "symbol": r.get("symbol"), "dir": r.get("dir"),
         "exit": r.get("exit"), "win": r.get("win"), "netR": r.get("netR")}
        for r in exits[-20:]
    ]
    out = {
        "trades_resolved": len(net_rs),
        "entries": len(entries),
        "skips_chop": len(skips),
        "win_rate_pct": round(wins / len(exits) * 100, 1) if exits else 0.0,
        "total_R": round(sum(net_rs), 3),
        "span_days": span_days,
        "trades_per_week": trades_per_week,
        **sig,
        "significant": significant,
        "cluster": cluster,
        "open_positions": {"count": len(open_syms), "symbols": open_syms},
        "open_stress": {"tstat_at_minus_half_R": stress_half["tstat"],
                        "tstat_at_minus_1R": stress_full["tstat"]},
        "power": _eta_to_power(net_rs, trades_per_week),
        "recent_trades": recent,
        "log_present": path.exists(),
    }
    if not net_rs:
        out["status"] = "accumulating — no resolved trades yet"
    elif significant:
        out["status"] = "LIVE EDGE CONFIRMED (cluster |t|>=2, p<0.05, holds with opens at -0.5R)"
    elif sig["significant"]:
        out["status"] = ("per-trade t inflated by same-bar clustering/open book — "
                         "not significant at the bar level yet")
    else:
        out["status"] = "accumulating — not yet significant"
    return out


def live_significance() -> dict[str, Any]:
    return {lane: lane_significance(path) for lane, path in LANES.items()}


if __name__ == "__main__":
    import sys
    json.dump(live_significance(), sys.stdout, indent=2)
    print()
