"""Alpha Zoo benchmark — run every published factor through the lab's REAL
fee-accurate engine + significance layer, under cumulative Bonferroni.

This is the honest version of "benchmark 452 alphas": a curated, pre-registered
set of single-asset factors (alpha_zoo.ZOO), each judged by the same HAC t-stat
and bootstrap p-value the rest of the lab uses, with the significance bar
deflated to alpha/N because we are testing N of them at once.

Reuses the engine by registering each factor as a transient StrategySpec in the
in-memory STRATEGIES dict — no edits to strategies/__init__.py (Hermes owns the
working tree there). Numbers therefore match /api/backtest exactly.

Usage:
    python -m alpha_bench --fixture SOL-365d-Min15 --fee-bps 7.5
    python -m alpha_bench --fixture DOGE-365d-Min15 --interval 15m
    python -m alpha_bench --csv /path/to/ohlcv.csv --interval 1d
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from alpha_zoo import ZOO, bonferroni_alpha
from engine import run_backtest
from stats import significance
from strategies import STRATEGIES
from strategies.base import StrategySpec


def _load_fixture(stem: str) -> pd.DataFrame:
    from providers.azc_fixture import AzcFixtureProvider
    from providers.base import DatasetRequest

    prov = AzcFixtureProvider()
    # years=0 → no trim; take the whole tape.
    resp = prov.fetch(DatasetRequest(symbol=stem, interval="15m", years=0))
    return resp.df


def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Positional OHLCV resample to a slower bar (e.g. '1D'). Fewer bars =
    less rebalancing = the turnover-fee test for the Alpha Zoo open thread."""
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    cols = {k: v for k, v in agg.items() if k in df.columns}
    out = df.resample(rule).agg(cols).dropna(how="any")
    return out


def _load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    # be liberal about column casing / a time column
    cols = {c.lower(): c for c in df.columns}
    tcol = cols.get("time") or cols.get("date") or cols.get("timestamp") or df.columns[0]
    df.index = pd.to_datetime(df[tcol], utc=True, errors="coerce")
    rename = {}
    for want in ("Open", "High", "Low", "Close", "Volume"):
        if want in df.columns:
            continue
        src = cols.get(want.lower())
        if src:
            rename[src] = want
    df = df.rename(columns=rename)
    keep = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in df.columns]
    return df[keep].dropna(how="all").sort_index()


def _register_factor_strategies() -> list[str]:
    """Inject each zoo factor as a transient close-to-close strategy. Returns
    the registered names. In-process only; never written to disk."""
    names = []
    for f in ZOO:
        name = f"zoo__{f.name}"

        def _builder(df: pd.DataFrame, params: dict[str, Any], _fn=f.signal) -> pd.Series:
            return _fn(df)

        STRATEGIES[name] = StrategySpec(
            name=name,
            label=f"Zoo: {f.name} [{f.source}]",
            params={},
            builder=_builder,
            execution="position",
            tags=["alpha-zoo", f.source],
        )
        names.append(name)
    return names


def run_benchmark(
    df: pd.DataFrame,
    interval: str = "15m",
    fee_bps: float = 7.5,
    alpha: float = 0.05,
) -> dict[str, Any]:
    names = _register_factor_strategies()
    n = len(names)
    bar = bonferroni_alpha(alpha, n)

    rows: list[dict[str, Any]] = []
    for f, name in zip(ZOO, names):
        try:
            result = run_backtest(
                df=df, strategy_name=name, params={},
                fee_bps=fee_bps, interval=interval,
            )
            sig = significance(result.curve)
            m = result.metrics
            rows.append({
                "factor": f.name,
                "source": f.source,
                "total_return": round(float(m.get("total_return", 0.0)), 4),
                "sharpe": round(float(m.get("sharpe", 0.0)), 3),
                "trades": int(m.get("trades", m.get("num_trades", 0)) or 0),
                "n": sig["n"],
                "tstat": sig["tstat"],
                "pvalue": sig["pvalue"],
                # Bonferroni-deflated verdict: must clear alpha/N AND |t|>=2.
                "passes_bonferroni": bool(sig["pvalue"] < bar and abs(sig["tstat"]) >= 2.0),
                "raw_significant": sig["significant"],
            })
        except Exception as e:  # one bad factor must not sink the run
            rows.append({"factor": f.name, "source": f.source, "error": str(e)})

    ranked = sorted(
        rows,
        key=lambda r: (r.get("passes_bonferroni", False), abs(r.get("tstat", 0.0) or 0.0)),
        reverse=True,
    )
    survivors = [r["factor"] for r in ranked if r.get("passes_bonferroni")]
    return {
        "n_factors": n,
        "alpha": alpha,
        "bonferroni_bar": round(bar, 5),
        "fee_bps": fee_bps,
        "interval": interval,
        "bars": int(len(df)),
        "survivors": survivors,
        "results": ranked,
    }


def _fmt_table(rep: dict[str, Any]) -> str:
    lines = [
        f"Alpha Zoo benchmark — {rep['n_factors']} factors, {rep['bars']} bars, "
        f"fee={rep['fee_bps']}bps, interval={rep['interval']}",
        f"Bonferroni bar: p < {rep['bonferroni_bar']} (= {rep['alpha']}/{rep['n_factors']}) AND |t| >= 2",
        "",
        f"{'factor':<22}{'src':<10}{'tot.ret':>9}{'sharpe':>8}{'t':>7}{'p':>9}  verdict",
        "-" * 78,
    ]
    for r in rep["results"]:
        if "error" in r:
            lines.append(f"{r['factor']:<22}{r['source']:<10}{'ERR':>9}  {r['error'][:30]}")
            continue
        verdict = "PASS ✓" if r["passes_bonferroni"] else ("(raw-sig)" if r["raw_significant"] else "noise")
        lines.append(
            f"{r['factor']:<22}{r['source']:<10}{r['total_return']:>9.3f}{r['sharpe']:>8.2f}"
            f"{r['tstat']:>7.2f}{r['pvalue']:>9.4f}  {verdict}"
        )
    lines.append("-" * 78)
    if rep["survivors"]:
        lines.append(f"SURVIVORS (cleared Bonferroni+HAC): {', '.join(rep['survivors'])}")
    else:
        lines.append("NO factor cleared the Bonferroni-deflated bar. Expected — this is the honest result.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Benchmark the Alpha Zoo with Bonferroni+HAC discipline.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--fixture", help="AZC fixture stem, e.g. SOL-365d-Min15")
    src.add_argument("--csv", help="Path to an OHLCV CSV")
    ap.add_argument("--interval", default="15m")
    ap.add_argument("--fee-bps", type=float, default=7.5, help="per-side fee in bps (MEXC taker ~7.5)")
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--resample", default=None, help="resample to a slower bar before testing, e.g. 1D, 4H (cuts turnover)")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = ap.parse_args(argv)

    df = _load_fixture(args.fixture) if args.fixture else _load_csv(args.csv)
    if args.resample and df is not None and not df.empty:
        df = _resample(df, args.resample)
        # interval label should follow the resampled bar so annualization is right
        if args.resample.upper() in ("1D", "D"):
            args.interval = "1d"
    if df is None or df.empty or len(df) < 80:
        print("Not enough data to benchmark (need >= 80 bars).", file=sys.stderr)
        return 2

    rep = run_benchmark(df, interval=args.interval, fee_bps=args.fee_bps, alpha=args.alpha)
    print(json.dumps(rep, indent=2) if args.json else _fmt_table(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
