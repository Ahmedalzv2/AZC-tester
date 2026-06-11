"""Forward significance tracker for the Alpaca paper NAV record.

Hard rule #1 gates live capital on a FORWARD t-stat clearing ~2. The crypto
shadow lanes have /api/live-significance for that; this is the equivalent for
the ETF trend lane — the only fundable edge in the stack. It reads
execution/alpaca-nav.jsonl (live-paper rows only), turns the NAV into daily
returns, and reports the honest clock:

- HAC (Newey-West) t-stat of the mean daily return + annualized Sharpe + max DD;
- years_to_t2 = (2 / Sharpe)^2 — at the backtest's Sharpe ~0.5-0.8 a standalone
  forward t=2 is a MULTI-YEAR clock, not a multi-month one. The tracker says so
  instead of letting a lucky quarter masquerade as proof;
- a MIN_DAYS gate so a hot first few weeks can't print significant=true — the
  exact per-trade inflation the crypto lane already burned us on (2026-06-10).

Run: .venv/bin/python -m execution.forward_significance
Writes execution/forward-significance.json for the dashboard/digest to read.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stats import newey_west_tstat  # noqa: E402

NAV_LOG = Path(__file__).resolve().parent / "alpaca-nav.jsonl"
OUT = Path(__file__).resolve().parent / "forward-significance.json"
TRADING_DAYS = 252
MIN_DAYS = 60  # below this, any t-stat is noise — never flag significant


def nav_returns(rows: list[dict]) -> list[float]:
    """Daily returns from live-paper NAV rows; dedupe by date keeping the last."""
    by_date: dict[str, float] = {}
    for r in rows:
        if r.get("mode") != "live-paper":
            continue
        eq = r.get("equity")
        if isinstance(eq, (int, float)) and eq > 0:
            by_date[str(r.get("date", ""))] = float(eq)
    equity = [by_date[d] for d in sorted(by_date)]
    return [equity[i] / equity[i - 1] - 1.0 for i in range(1, len(equity))]


def _max_drawdown_pct(returns: list[float]) -> float:
    eq, peak, dd = 1.0, 1.0, 0.0
    for r in returns:
        eq *= 1.0 + r
        peak = max(peak, eq)
        dd = min(dd, eq / peak - 1.0)
    return dd * 100.0


def forward_report(rows: list[dict]) -> dict:
    """Pure verdict on the forward NAV record. Honest by construction."""
    rets = nav_returns(rows)
    n = len(rets)
    if n < 2:
        return {
            "n_days": n, "total_return_pct": 0.0, "hac_t": 0.0, "pvalue": 1.0,
            "sharpe_ann": 0.0, "max_dd_pct": 0.0, "years_to_t2": None,
            "min_days": MIN_DAYS, "significant": False,
            "status": f"accumulating — {n} daily return(s), need >= {MIN_DAYS}",
        }

    import numpy as np
    x = np.asarray(rets, dtype=float)
    t = newey_west_tstat(x)
    pvalue = 0.5 * math.erfc(t / math.sqrt(2.0))  # one-sided, mean > 0
    std = float(x.std(ddof=1))
    sharpe = float(x.mean()) / std * math.sqrt(TRADING_DAYS) if std > 0 else 0.0
    total = (float(np.prod(1.0 + x)) - 1.0) * 100.0
    # t ~= Sharpe * sqrt(years): the honest funding clock at the CURRENT Sharpe
    years_to_t2 = (2.0 / sharpe) ** 2 if sharpe > 0 else None

    significant = n >= MIN_DAYS and t >= 2.0 and pvalue < 0.05
    if significant:
        status = "FORWARD EDGE CONFIRMED (HAC t>=2 on >=60 independent days)"
    elif n < MIN_DAYS:
        status = (f"accumulating — {n}/{MIN_DAYS} days; t-stat not judged below "
                  f"{MIN_DAYS} days (small-n inflation)")
    else:
        eta = f"~{years_to_t2:.1f}y to t=2 at current Sharpe" if years_to_t2 else "no positive edge yet"
        status = f"not significant — {eta}"

    return {
        "n_days": n, "total_return_pct": round(total, 3),
        "hac_t": round(t, 3), "pvalue": round(pvalue, 5),
        "sharpe_ann": round(sharpe, 3), "max_dd_pct": round(_max_drawdown_pct(rets), 3),
        "years_to_t2": round(years_to_t2, 2) if years_to_t2 is not None else None,
        "min_days": MIN_DAYS, "significant": significant, "status": status,
    }


def _main() -> int:
    rows = []
    if NAV_LOG.exists():
        for line in NAV_LOG.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    rep = forward_report(rows)
    OUT.write_text(json.dumps(rep, indent=2) + "\n")
    print(f"[forward-sig] n={rep['n_days']}d  total={rep['total_return_pct']:+.2f}%  "
          f"HAC t={rep['hac_t']:.2f}  Sharpe={rep['sharpe_ann']:.2f}  "
          f"maxDD={rep['max_dd_pct']:.1f}%  -> {rep['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
