"""Continuous, disciplined strategy search.

Grids many entry-signal families x params x markets through the fee-accurate
bracket engine, validates every config OUT-OF-SAMPLE, and applies a
multiple-testing penalty — because testing N configs guarantees ~N*alpha fake
"winners" by chance. A config is only a *candidate* if it clears the
Bonferroni-deflated bar on held-out data AND is positive in-sample too. Even
then it's a hypothesis: the verdict is the live shadow forward-test, not this.

Run: `python strategy_hunt.py`  (appends one run to hunt-results.jsonl)
Designed to be run repeatedly on a timer; each run records its trial count and
any survivors so the search history is auditable.
"""
from __future__ import annotations

import itertools
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from bracket_signals import SIGNALS, simulate_signal
from engine_bracket import Bar, resample_positional
from stats import _default_lags, bootstrap_pvalue, newey_west_tstat

FIX = Path("/root/apps/ict-autopilot/tests/fixtures")
RESULTS = Path(__file__).resolve().parent / "hunt-results.jsonl"
TAKER = {"makerEntry": False, "makerTp": False, "takerRate": 0.00075, "slipBps": 0}

# 5y hourly crypto -> 4h. The deepest, cleanest tape we have locally.
MARKETS = {
    "DOGE": ("DOGE-1825d-Min60.json", 4),
    "SOL": ("SOL-1825d-Min60.json", 4),
    "XRP": ("XRP-1825d-Min60.json", 4),
}
OOS_FRACTION = 0.30
MIN_OOS_TRADES = 40


def _load(name, per):
    raw = json.loads((FIX / name).read_text())
    base = [Bar(t=(r["t"] if isinstance(r, dict) else r[0]),
                o=float(r["o"] if isinstance(r, dict) else r[1]),
                h=float(r["h"] if isinstance(r, dict) else r[2]),
                l=float(r["l"] if isinstance(r, dict) else r[3]),
                c=float(r["c"] if isinstance(r, dict) else r[4])) for r in raw]
    return resample_positional(base, per)


def _grids() -> list[tuple[str, dict[str, Any]]]:
    """(signal_name, params) configs. Bounded so Bonferroni stays tractable."""
    out: list[tuple[str, dict[str, Any]]] = []
    atrm = [2, 3]
    trails = [2, 3, 4]
    rrs = [1.0, 1.5, 2.0]
    dons = [20, 30, 55]
    for am in atrm:
        base = {"atrN": 14, "atrMult": am, **TAKER}
        for don in dons:
            for tr in trails:  # donchian trend (trail exit), gated + ungated
                for er in (0.0, 0.30):
                    out.append(("donchian_break", {**base, "don": don, "rr": 99, "trail": tr, "erMin": er, "regimeN": 20}))
            for rr in rrs:  # donchian fade (target exit)
                out.append(("donchian_fade", {**base, "don": don, "rr": rr}))
        for mom in (10, 20, 40):
            out.append(("ts_momentum", {**base, "mom": mom, "rr": 99, "trail": 3}))
        for fast, slow in ((10, 30), (20, 50), (50, 100)):
            out.append(("ma_cross", {**base, "fast": fast, "slow": slow, "rr": 99, "trail": 3}))
        for lo, hi in ((30, 70), (20, 80)):
            for rr in (1.0, 1.5):
                out.append(("rsi_reversion", {**base, "rsi_n": 14, "lower": lo, "upper": hi, "rr": rr}))
        for k in (2.0, 2.5):
            out.append(("bollinger_break", {**base, "bb_n": 20, "bb_k": k, "rr": 99, "trail": 3}))
            for rr in (1.0, 1.5):
                out.append(("bollinger_fade", {**base, "bb_n": 20, "bb_k": k, "rr": rr}))
    return out


def _sig(net_rs: list[float]) -> dict[str, Any]:
    arr = np.asarray(net_rs, dtype=float)
    n = arr.size
    if n < 2:
        return {"n": n, "mean": 0.0, "t": 0.0, "p": 1.0}
    return {"n": n, "mean": float(arr.mean()),
            "t": float(newey_west_tstat(arr, lags=_default_lags(n))),
            "p": float(bootstrap_pvalue(arr))}


# Worker-process state: markets/splits loaded once per process (not pickled
# per task) so multiprocessing overhead stays low on small datasets.
_SPLITS: dict[str, tuple] = {}


def _init_worker():
    markets = {m: _load(f, per) for m, (f, per) in MARKETS.items() if (FIX / f).exists()}
    for m, bars in markets.items():
        k = int(len(bars) * (1 - OOS_FRACTION))
        _SPLITS[m] = (bars[:k], bars[k:])


def _eval_config(arg, splits=None, alpha_deflated=1.0):
    """Run one config across all markets, IS + OOS. Pure → safe to parallelize."""
    sig_name, params = arg
    splits = splits if splits is not None else _SPLITS
    fn = SIGNALS[sig_name]
    is_rs, oos_rs = [], []
    for isb, oosb in splits.values():
        is_rs += [t["netR"] for t in simulate_signal(isb, fn, params)]
        oos_rs += [t["netR"] for t in simulate_signal(oosb, fn, params)]
    iss, oss = _sig(is_rs), _sig(oos_rs)
    is_candidate = (
        oss["n"] >= MIN_OOS_TRADES and oss["mean"] > 0 and iss["mean"] > 0
        and oss["t"] >= 2.0 and oss["p"] < alpha_deflated
    )
    return {
        "signal": sig_name,
        "params": {k: v for k, v in params.items() if k not in TAKER},
        "is_n": iss["n"], "is_netR": round(iss["mean"], 4), "is_t": round(iss["t"], 2),
        "oos_n": oss["n"], "oos_netR": round(oss["mean"], 4), "oos_t": round(oss["t"], 2),
        "oos_p": round(oss["p"], 4),
        "candidate": bool(is_candidate),
    }


def run_hunt(timestamp_ms: int | None = None, workers: int | None = None) -> dict[str, Any]:
    import os
    from concurrent.futures import ProcessPoolExecutor
    from functools import partial

    markets = {m: _load(f, per) for m, (f, per) in MARKETS.items() if (FIX / f).exists()}
    if not markets:
        return {"error": "no fixtures mounted", "candidates": [], "trials": 0}
    splits = {}
    for m, bars in markets.items():
        k = int(len(bars) * (1 - OOS_FRACTION))
        splits[m] = (bars[:k], bars[k:])

    configs = _grids()
    trials = len(configs)
    alpha_deflated = 0.05 / trials  # Bonferroni: control family-wise error

    # Parallelize across cores. On a tiny box this is a ~core-count speedup at
    # best — compute was never the bottleneck (data/power/forward-time are), but
    # a faster search lets us explore broader grids per run.
    n_workers = workers if workers is not None else max(1, (os.cpu_count() or 2))
    if n_workers > 1 and trials > 8:
        with ProcessPoolExecutor(max_workers=n_workers, initializer=_init_worker) as ex:
            rows = list(ex.map(partial(_eval_config, alpha_deflated=alpha_deflated), configs, chunksize=8))
    else:
        rows = [_eval_config(c, splits=splits, alpha_deflated=alpha_deflated) for c in configs]

    rows.sort(key=lambda r: -r["oos_t"])
    candidates = [r for r in rows if r["candidate"]]
    run = {
        "ts": timestamp_ms,
        "trials": trials,
        "alpha_deflated": alpha_deflated,
        "markets": list(markets),
        "oos_fraction": OOS_FRACTION,
        "n_candidates": len(candidates),
        "candidates": candidates,
        "top": rows[:10],
    }
    return run


def append_result(run: dict[str, Any]) -> None:
    with RESULTS.open("a") as f:
        f.write(json.dumps(run) + "\n")


if __name__ == "__main__":
    import sys

    run = run_hunt()
    print(f"trials={run.get('trials')}  candidates={run.get('n_candidates')}  "
          f"deflated_alpha={run.get('alpha_deflated', 0):.2e}")
    print(f"{'signal':16}{'params':46}{'IS_netR':>8}{'IS_t':>6}{'OOS_netR':>9}{'OOS_t':>6}{'OOS_p':>8}  cand")
    for r in run.get("top", []):
        ps = ",".join(f"{k}={v}" for k, v in r["params"].items())[:44]
        flag = "  <-- CANDIDATE" if r["candidate"] else ""
        print(f"{r['signal']:16}{ps:46}{r['is_netR']:>+8.3f}{r['is_t']:>+6.2f}"
              f"{r['oos_netR']:>+9.3f}{r['oos_t']:>+6.2f}{r['oos_p']:>8.3f}{flag}")
    if "--save" in sys.argv:
        append_result(run)
        print(f"appended to {RESULTS.name}")
