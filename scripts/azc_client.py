#!/usr/bin/env python3
"""Minimal stdlib client for the AZC Tester API.

Used by the /test-strategy agent loop to fire a custom strategy at the
backtester and read back the edge verdict. No third-party deps (urllib only)
so it runs on the bare VPS host, outside the container.

Config via env:
  TESTER_URL   base URL of the tester        (default http://127.0.0.1:3016)
  AZC_API_KEY  API key when auth is on; falls back to reading AZC_API_KEY from
               <gallant>/.env if the env var is unset.

Examples:
  python scripts/azc_client.py --symbol BTC-USD --interval 1d \
      --strategy-file /tmp/strat.py --params '{"n":20}' --walkforward
  AZC_API_KEY=... TESTER_URL=https://backtest-gallant.srv1688368.hstgr.cloud \
      python scripts/azc_client.py --symbol SPY --strategy-file /tmp/s.py
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

TESTER_URL = os.environ.get("TESTER_URL", "http://127.0.0.1:3016").rstrip("/")
ENV_FALLBACK = Path(os.environ.get("AZC_ENV_FILE", "/root/apps/backtest-lab-gallant/.env"))


def _api_key() -> str:
    key = os.environ.get("AZC_API_KEY", "").strip()
    if key:
        return key
    if ENV_FALLBACK.exists():
        for line in ENV_FALLBACK.read_text().splitlines():
            if line.strip().startswith("AZC_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _post(path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    key = _api_key()
    if key:
        headers["X-API-Key"] = key
    req = urllib.request.Request(TESTER_URL + path, data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=900) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise SystemExit(f"HTTP {exc.code} from {path}: {body}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"Cannot reach tester at {TESTER_URL}: {exc}")


def _payload(args: argparse.Namespace, code: str) -> dict:
    payload = {
        "data_provider": args.provider,
        "symbol": args.symbol,
        "interval": args.interval,
        "years": args.years,
        "strategy": "custom_python",
        "strategy_params": json.loads(args.params or "{}"),
        "custom_code": code,
        "initial_cash": args.initial_cash,
        "fee_bps": args.fee_bps,
    }
    if args.file_path:
        payload["file_path"] = args.file_path
    return payload


def _summary(resp: dict) -> dict:
    metrics = resp.get("metrics", {}) or {}
    report = metrics.get("report", {}) or {}
    sig = resp.get("significance", {}) or {}
    return {
        "run_id": (resp.get("saved") or {}).get("id"),
        "symbol": (resp.get("source") or {}).get("symbol"),
        "total_return_pct": metrics.get("total_return_pct"),
        "profit_factor": report.get("profit_factor"),
        "sharpe": report.get("sharpe"),
        "sortino": report.get("sortino"),
        "max_drawdown_pct": report.get("max_drawdown_pct"),
        "win_rate_pct": metrics.get("win_rate_pct"),
        "trades": metrics.get("trade_count"),
        "tstat": sig.get("tstat"),
        "pvalue": sig.get("pvalue"),
        "significant": sig.get("significant"),
    }


def _wf_leg(leg: dict | None) -> dict | None:
    if not leg:
        return None
    metrics = leg.get("metrics", {}) or {}
    sig = leg.get("significance", {}) or {}
    return {
        "return_pct": metrics.get("total_return_pct"),
        "tstat": sig.get("tstat"),
        "pvalue": sig.get("pvalue"),
        "significant": sig.get("significant"),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Fire a custom strategy at the AZC Tester.")
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--interval", default="1d")
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--provider", default="yahoo")
    ap.add_argument("--file-path", dest="file_path", default=None, help="for data_provider=local_file")
    ap.add_argument("--strategy-file", dest="strategy_file", required=True, help="path to a .py with build_signals(df, params)")
    ap.add_argument("--params", default="{}", help="JSON dict of strategy params")
    ap.add_argument("--initial-cash", dest="initial_cash", type=float, default=10000)
    ap.add_argument("--fee-bps", dest="fee_bps", type=float, default=7)
    ap.add_argument("--walkforward", action="store_true", help="also run an out-of-sample holdout")
    args = ap.parse_args()

    code = Path(args.strategy_file).read_text()
    resp = _post("/api/backtest", _payload(args, code))
    out = {"backtest": _summary(resp)}
    if args.walkforward:
        wf = _post("/api/walkforward", {**_payload(args, code), "oos_fraction": 0.3})
        out["walkforward"] = {
            "holds_out_of_sample": wf.get("holds_out_of_sample"),
            "decay": wf.get("decay"),
            "in_sample": _wf_leg(wf.get("in_sample")),
            "out_sample": _wf_leg(wf.get("out_sample")),
        }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
