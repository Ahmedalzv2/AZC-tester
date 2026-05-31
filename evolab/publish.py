"""Publish an EvoLab genome's backtest into a tester's Browse run-store.

Two legs share this module:
  - the daemon promotes a *real* champion to the gallant showcase, and
  - the operator runs a pasted strategy once into the main lab + seeds it.

The store write is NOT done here (the daemon is a separate process from the
tester): build_run_payload runs the genome through EvoLab's OWN simulator
(`bracket_signals.simulate_signal`, fees applied via TAKER) so Browse shows
exactly what EvoLab scored, then post_ingest() ships the payload to the tester's
POST /api/runs/ingest, which owns its store.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np

from bracket_signals import SIGNALS, simulate_signal
from engine_bracket import bracket_metrics
from evolab import data, fitness
from evolab.genome import FIXED_PARAMS, PARAM_SCHEMAS, Genome

INTERVAL = "4h"                 # EvoLab fixtures are 4h bars
DEFAULT_RISK_PCT = 0.005        # account risk per trade
FEE_BPS = round(float(data.TAKER["takerRate"]) * 1e4, 2)  # 7.5 bps all-taker


def build_equity_curve(net_rs: list[float], risk_pct: float) -> list[dict[str, Any]]:
    """Equity + drawdown series for the gallant report charts. The Browse detail
    view calls renderCharts(response.curve) and does curve.map(...), so an ingested
    run with no curve throws and the whole report blanks. equity is an index from
    100 stepped by netR*risk; drawdown is running peak-to-trough %."""
    curve, eq, peak = [], 100.0, 100.0
    for i, r in enumerate(net_rs, start=1):
        eq += float(r) * risk_pct * 100.0
        peak = max(peak, eq)
        dd = (eq / peak - 1.0) * 100.0 if peak else 0.0
        curve.append({"time": i, "equity": round(eq, 3), "drawdown": round(dd, 3)})
    return curve


def _assemble_payload(asset: str, genome: Genome, trades: list[dict[str, Any]],
                      verdict: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Pure: map a genome + its trades + an honest `fitness.assess` verdict into
    the (request_payload, response_payload) pair that save_run/ingest expects."""
    bm = bracket_metrics(trades)  # {"n","winPct","netR","totalR","maxDD"} in R units
    risk_pct = float(genome.params.get("riskPct", DEFAULT_RISK_PCT))
    net_rs = np.asarray([t["netR"] for t in trades], dtype=float)
    sharpe = float(net_rs.mean() / (net_rs.std() + 1e-9)) if net_rs.size else 0.0
    oos = verdict.get("oos", {})

    metrics = {
        "trade_count": bm["n"],
        "win_rate_pct": round(bm["winPct"], 3),
        "total_r": round(bm["totalR"], 4),
        "net_r_per_trade": round(bm["netR"], 4),
        "max_drawdown_r": round(bm["maxDD"], 4),
        # account-level views (R scaled by per-trade risk), clearly derived:
        "total_return_pct": round(bm["totalR"] * risk_pct * 100, 3),
        "max_drawdown_pct": round(-bm["maxDD"] * risk_pct * 100, 3),
        "sharpe": round(sharpe, 3),
        "strategy": f"evolab:{genome.family}",
        "interval": INTERVAL,
        "fee_bps": FEE_BPS,
        "fee_model": "all-taker",
        "execution": "bracket",
    }
    significance = {
        "tstat": oos.get("t", 0.0),
        "pvalue": oos.get("p", 1.0),
        "mean_return": oos.get("meanR", 0.0),
        "n": oos.get("n", 0),
        "significant": verdict.get("verdict") == "real",
        "verdict": verdict.get("verdict", "noise"),
        "scope": "oos",
    }
    request_payload = {
        "strategy": f"evolab:{genome.family}",
        "data_provider": "azc_fixture",
        "symbol": asset,
        "interval": INTERVAL,
        "years": 0,
        "strategy_params": dict(genome.params),
    }
    response_payload = {
        "metrics": metrics,
        "significance": significance,
        "trades": trades,
        "curve": build_equity_curve([t["netR"] for t in trades], risk_pct),
        "source": {"provider": "evolab", "note": "EvoLab genome via simulate_signal (all-taker)"},
        "evolab": {
            "family": genome.family,
            "params": dict(genome.params),
            "verdict": verdict.get("verdict"),
            "net_R_oos": verdict.get("net_R_oos"),
            "is": verdict.get("is"),
            "oos": oos,
        },
    }
    return request_payload, response_payload


def _fill_params(family: str, params: dict[str, Any]) -> dict[str, Any]:
    """Fill any params the family's schema needs but the caller omitted, using
    the schema's first choice / low bound. Lets a partially-specified (e.g.
    operator-pasted) genome still run; fully-evolved genomes pass through
    unchanged."""
    out = dict(params)
    for name, spec in PARAM_SCHEMAS.get(family, {}).items():
        if name not in out:
            out[name] = spec.choices[0] if spec.choices else spec.low
    return out


def build_run_payload(asset: str, genome: Genome) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load the asset, score the genome honestly (IS/OOS, fees applied), and
    assemble the Browse payload. Missing params are filled from the family schema."""
    bars = data.load_asset(asset)
    is_bars, oos_bars = data.split(bars)
    genome = Genome(genome.family, _fill_params(genome.family, genome.params))
    verdict = fitness.assess(genome.family, genome.params, is_bars, oos_bars)
    params = {**genome.params, **FIXED_PARAMS.get(genome.family, {}), **data.TAKER}
    full_trades = simulate_signal(bars, SIGNALS[genome.family], params)
    return _assemble_payload(asset, genome, full_trades, verdict)


# --- shipping the payload to a tester -------------------------------------

DEFAULT_URL = os.environ.get("TESTER_URL", "http://127.0.0.1:3015").rstrip("/")


def _api_key() -> str:
    key = os.environ.get("AZC_API_KEY", "").strip()
    if key:
        return key
    env = Path(__file__).resolve().parent.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.strip().startswith("AZC_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def post_ingest(request_payload: dict[str, Any], response_payload: dict[str, Any],
                base_url: str = DEFAULT_URL, api_key: str | None = None) -> str:
    body = json.dumps({"request_payload": request_payload,
                       "response_payload": response_payload}).encode()
    headers = {"Content-Type": "application/json"}
    key = api_key if api_key is not None else _api_key()
    if key:
        headers["X-API-Key"] = key
    req = urllib.request.Request(base_url.rstrip("/") + "/api/runs/ingest", data=body,
                                 method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    # the local lab returns {"run_id": ...}; the gallant deploy {"saved": {"id": ...}}
    return data.get("run_id") or data.get("saved", {}).get("id", "")


def publish_genome(asset: str, genome: Genome, base_url: str = DEFAULT_URL,
                   api_key: str | None = None) -> str:
    request_payload, response_payload = build_run_payload(asset, genome)
    return post_ingest(request_payload, response_payload, base_url=base_url, api_key=api_key)


def _main(argv: list[str] | None = None) -> int:
    import argparse
    from evolab.search import STATE_DIR
    from evolab.store import Store

    ap = argparse.ArgumentParser(prog="evolab.publish",
                                 description="Run an EvoLab genome, publish it to a tester, optionally seed it.")
    ap.add_argument("asset")
    ap.add_argument("--family", required=True, choices=sorted(SIGNALS.keys()))
    ap.add_argument("--params", default="{}", help="JSON dict of strategy params")
    ap.add_argument("--seed", action="store_true", help="also inject the genome into the asset population")
    ap.add_argument("--no-publish", action="store_true", help="skip the publish (seed only)")
    ap.add_argument("--url", default=DEFAULT_URL, help="tester base URL (default the main lab)")
    args = ap.parse_args(argv)

    genome = Genome(args.family, json.loads(args.params))
    if not args.no_publish:
        run_id = publish_genome(args.asset, genome, base_url=args.url)
        print(f"published run_id={run_id}  -> {args.url}")
    if args.seed:
        Store(STATE_DIR).seed_genome(args.asset, genome)
        print(f"seeded {args.family} into {args.asset} population")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
