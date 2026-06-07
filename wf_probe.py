"""Ephemeral workflow probe — headless backtest, NO DB persistence.

Used by the strategy-search workflow so the bulk grid does not flood the
tester dashboard's run history. Only deliberately-ingested finalists should
appear there. Safe to delete after the search.

Usage:
  python3 wf_probe.py '{"provider":"azc_fixture","symbol":"SOL-1095d-Min60",
                        "interval":"1h","strategy":"azc_trend","params":{},
                        "fee_bps":7.5,"oos_fraction":0.0}'

oos_fraction > 0 evaluates the SAME fixed params on the trailing slice only
(an honest out-of-sample stability check for a non-fitted config).
Prints one compact JSON line: metrics + HAC significance, or {"error": ...}.
"""
from __future__ import annotations

import json
import sys

from data_source import fetch_history
from engine import run_backtest
from stats import significance as _sig


def _run_one(spec: dict) -> dict:
    provider = spec.get("provider", "azc_fixture")
    symbol = spec["symbol"].strip()
    interval = spec.get("interval", "1h")
    strategy = spec["strategy"]
    params = dict(spec.get("params", {}) or {})
    fee_bps = float(spec.get("fee_bps", 7.5))
    oos = float(spec.get("oos_fraction", 0.0) or 0.0)

    # GOTCHA: the bracket engine (azc_trend/azc_meanrev) IGNORES fee_bps and
    # prices fees off params.takerRate. So fee_bps is a no-op there unless we
    # translate it. Map fee_bps -> takerRate for bracket strategies when the
    # caller did not pin takerRate explicitly, so the fee lever is honest.
    if strategy in ("azc_trend", "azc_meanrev") and "takerRate" not in params:
        params["takerRate"] = fee_bps / 10_000.0

    out: dict = {
        "symbol": symbol,
        "strategy": strategy,
        "fee_bps": fee_bps,
        "oos_fraction": oos,
        "params": params,
    }
    try:
        df, _src = fetch_history(
            symbol=symbol, interval=interval, years=spec.get("years", 5),
            refresh=False, provider=provider,
        )
        if oos > 0 and df is not None and len(df) > 50:
            cut = int(len(df) * (1.0 - oos))
            df = df.iloc[cut:]
        res = run_backtest(df=df, strategy_name=strategy, params=params,
                           fee_bps=fee_bps, interval=interval)
        m = res.metrics or {}
        sig = m.get("significance") or _sig(res.curve)
        out.update({
            "trades": m.get("trade_count"),
            "netR_per_trade": m.get("net_r_per_trade"),
            "total_r": m.get("total_r"),
            "win_rate_pct": m.get("win_rate_pct"),
            "total_return_pct": m.get("total_return_pct"),
            "sharpe": m.get("sharpe"),
            "max_dd_pct": m.get("max_drawdown_pct"),
            "fee_model": m.get("fee_model"),
            "tstat": (sig or {}).get("tstat"),
            "pvalue": (sig or {}).get("pvalue"),
            "n_sig": (sig or {}).get("n"),
            "significant": (sig or {}).get("significant"),
        })
    except Exception as exc:  # noqa: BLE001 — probe must always emit a line
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def main() -> None:
    payload = json.loads(sys.argv[1])
    specs = payload if isinstance(payload, list) else [payload]
    for spec in specs:
        print(json.dumps(_run_one(spec)), flush=True)


if __name__ == "__main__":
    main()
