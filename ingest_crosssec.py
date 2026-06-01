"""Ingest the cross-sectional momentum run into the lab/tester store so it is
visible in Browse on backtest.srv...cloud, using the SAME /api/runs/ingest path
EvoLab uses. Honest by construction: full-sample strength is shown, but the
significance block reports the OOS verdict (t=1.67 < 2 -> significant=false,
verdict 'candidate'), so it does NOT masquerade as a cleared champion and is NOT
pushed to the real-only gallant showcase. It earns gallant only when the forward
shadow t clears ~2.

Strategy class is cross-sectional (ranks the whole liquid universe), which the
per-asset EvoLab genome framework can't represent — hence a direct ingest, not a
genome publish.
"""
from __future__ import annotations

import json
import math
import urllib.request

from mexc_trend_hunt import DATA, hac_t
from cross_sectional_mexc import build_panel
from evolab.publish import report_block

LB, HOLD, FRAC, FEE, LIQ_TOP = 14, 7, 0.10, 0.00075, 100
LAB = "http://127.0.0.1:3015"


def series():
    man = {m["symbol"]: m["med_qvol"] for m in json.loads((DATA / "_manifest.json").read_text())}
    dates, by_sym, allsyms = build_panel()
    syms = sorted(allsyms, key=lambda s: -man.get(s, 0))[:LIQ_TOP]
    trades, prev = [], {}
    t = LB
    while t + HOLD < len(dates):
        dn, dp, df = dates[t], dates[t - LB], dates[t + HOLD]
        elig = [(s, by_sym[s][dn] / by_sym[s][dp] - 1) for s in syms
                if dn in by_sym[s] and dp in by_sym[s] and df in by_sym[s] and by_sym[s][dp] > 0]
        if len(elig) < 20:
            t += HOLD
            continue
        elig.sort(key=lambda x: x[1])
        k = max(1, int(len(elig) * FRAC))
        win = [s for s, _ in elig[-k:]]
        los = [s for s, _ in elig[:k]]
        w = {s: 0.5 / k for s in win}
        w.update({s: -0.5 / k for s in los})
        gross = sum(w[s] * (by_sym[s][df] / by_sym[s][dn] - 1) for s in w)
        keys = set(w) | set(prev)
        turn = sum(abs(w.get(s, 0) - prev.get(s, 0)) for s in keys)
        net = gross - turn * FEE
        trades.append({"netR": net, "grossR": gross, "ts": dn * 1000, "exit_ts": df * 1000,
                       "dir": "L/S", "entry": None, "exit": None, "bars": HOLD})
        prev = w
        t += HOLD
    return trades


def main() -> None:
    trades = series()
    nets = [t["netR"] for t in trades]
    cut = int(len(nets) * 0.7)
    oos = nets[cut:]
    full_t = hac_t(nets)
    oos_t = hac_t(oos)
    oos_mean = sum(oos) / len(oos)
    oos_p = math.erfc(abs(oos_t) / math.sqrt(2))      # two-sided normal tail
    mean = sum(nets) / len(nets)
    sd = (sum((x - mean) ** 2 for x in nets) / len(nets)) ** 0.5
    sharpe = mean / sd * math.sqrt(365 / HOLD)

    # reuse the platform's own report builder (risk_pct=1 -> equity in % points)
    curve, dollar_trades, report = report_block(trades, risk_pct=1.0)

    metrics = {
        "report": report,
        "trade_count": len(trades),
        "win_rate_pct": round(100 * sum(1 for x in nets if x > 0) / len(nets), 2),
        "total_return_pct": round(sum(nets) * 100, 2),
        "sharpe": round(sharpe, 3),
        "full_sample_hac_t": round(full_t, 2),
        "strategy": "cross_sectional_momentum:top100liquid",
        "interval": "1d",
        "rebalance": "weekly(7d)",
        "lookback_days": LB,
        "book": "long top decile / short bottom decile, dollar-neutral",
        "fee_bps": 7.5,
        "fee_model": "all-taker",
        "execution": "cross-sectional-portfolio",
        "note": "Jegadeesh-Titman cross-sectional momentum on top-100-liquid MEXC perps. "
                "Full HAC t=3.73, bootstrap p<1e-4, every full year positive (2021-25). "
                "PAPER/forward-shadow CANDIDATE: OOS t=1.67<2 and 2026 YTD negative, NOT funded.",
    }
    significance = {
        "tstat": round(oos_t, 3),
        "pvalue": round(oos_p, 4),
        "mean_return": round(oos_mean, 5),
        "n": len(oos),
        "significant": False,                  # OOS t<2 -> not a cleared champion
        "verdict": "candidate",
        "scope": "oos",
    }
    request_payload = {
        "strategy": "cross_sectional_momentum:top100liquid",
        "data_provider": "mexc_daily_universe",
        "symbol": "MEXC top-100 liquid perps",
        "interval": "1d",
        "years": 5,
        "run_type": "backtest",
        "strategy_params": {"lookback_days": LB, "hold_days": HOLD, "decile": FRAC,
                            "universe": "top100_liquid", "fee_bps": 7.5, "neutral": True},
    }
    response_payload = {
        "metrics": metrics,
        "significance": significance,
        "trades": dollar_trades,
        "curve": curve,
        "source": {"provider": "cross_sectional_mexc",
                   "note": "Cross-sectional momentum (portfolio); ingested directly because the "
                           "per-asset EvoLab genome framework can't represent a ranked L/S book."},
    }
    body = json.dumps({"request_payload": request_payload,
                       "response_payload": response_payload}).encode()
    req = urllib.request.Request(LAB + "/api/runs/ingest", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        out = json.loads(resp.read().decode())
    print(f"ingested run_id={out.get('run_id')}  full_t={full_t:.2f} OOS_t={oos_t:.2f} "
          f"Sharpe={sharpe:.2f} periods={len(trades)} verdict=candidate")


if __name__ == "__main__":
    main()
