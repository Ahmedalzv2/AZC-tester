"""External replication: does the SAME cross-sectional momentum rule that scored
in liquid crypto also show on US large-cap equities? An independent universe =
out-of-sample-by-construction. If the Jegadeesh-Titman factor appears here under
the same locked logic, the crypto result is a real factor surfacing in crypto,
not a data-mined fluke.

Uses bar-count lookback/hold (not calendar days) so the rule is identical across
venues despite equities trading ~5/7 days. Fees ~5bp round-trip (equity L/S,
generous for borrow). HAC t on the per-period net return series + 70/30 OOS.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mexc_trend_hunt import hac_t

# ~80 liquid S&P large-caps (stable, long-listed, deep liquidity)
TICKERS = ("AAPL MSFT AMZN GOOGL META NVDA TSLA JPM V JNJ WMT PG MA HD BAC XOM "
           "DIS KO PEP CSCO INTC VZ ADBE CRM NFLX CMCSA PFE ABT TMO NKE MRK ORCL "
           "ACN COST AVGO TXN QCOM HON UNH LLY CVX WFC MCD MDT NEE PM LOW UPS MS "
           "GS BLK CAT BA AXP GE MMM IBM AMGN SBUX GILD MDLZ ISRG NOW INTU AMD "
           "BKNG ADP LRCX MU ZTS PYPL REGN VRTX PANW KLAC SNPS CDNS FTNT").split()
FEE = 0.0005  # ~5bp round-trip


def panel():
    df = yf.download(TICKERS, period="12y", interval="1d", auto_adjust=True,
                     progress=False, threads=True)["Close"]
    df = df.dropna(axis=1, thresh=int(len(df) * 0.8))  # drop tickers with thin history
    dates = list(df.index)
    by = {c: {i: float(v) for i, v in enumerate(df[c].tolist()) if v == v} for c in df.columns}
    return dates, by, list(df.columns)


def run(by, syms, n, *, lookback, hold, frac, fee, direction=1):
    rets, prev = [], {}
    t = lookback
    while t + hold < n:
        elig = [(s, by[s][t] / by[s][t - lookback] - 1) for s in syms
                if t in by[s] and t - lookback in by[s] and t + hold in by[s] and by[s][t - lookback] > 0]
        if len(elig) < 20:
            t += hold
            continue
        elig.sort(key=lambda x: x[1])
        k = max(1, int(len(elig) * frac))
        win = [s for s, _ in elig[-k:]]
        los = [s for s, _ in elig[:k]]
        w = {s: 0.5 / k * direction for s in win}
        w.update({s: -0.5 / k * direction for s in los})
        gross = sum(w[s] * (by[s][t + hold] / by[s][t] - 1) for s in w)
        keys = set(w) | set(prev)
        turn = sum(abs(w.get(s, 0) - prev.get(s, 0)) for s in keys)
        rets.append(gross - turn * fee)
        prev = w
        t += hold
    return rets


def stat(rets, hold):
    if len(rets) < 5:
        return 0, 0.0, 0.0, 0.0
    m = sum(rets) / len(rets)
    sd = (sum((x - m) ** 2 for x in rets) / len(rets)) ** 0.5
    sharpe = m / sd * math.sqrt(252 / hold) if sd else 0.0
    cut = int(len(rets) * 0.7)
    return len(rets), sharpe, hac_t(rets), hac_t(rets[cut:])


def main():
    dates, by, syms = panel()
    n = len(dates)
    print(f"equity panel: {len(syms)} tickers, {n} daily bars ({dates[0].date()}..{dates[-1].date()})\n")
    print(f"{'config':>26}{'periods':>9}{'Sharpe':>8}{'HACt':>7}{'OOSt':>7}")
    configs = [("crypto-analog 14bar/wk", 14, 5), ("classic 63bar/monthly", 63, 21),
               ("classic 126bar/monthly", 126, 21), ("classic 252bar/monthly", 252, 21)]
    for label, lb, hold in configs:
        np_, sh, t, ot = stat(run(by, syms, n, lookback=lb, hold=hold, frac=0.1, fee=FEE), hold)
        print(f"{label:>26}{np_:>9}{sh:>+8.2f}{t:>+7.2f}{ot:>+7.2f}")
    # reversal check at the classic config (sign confirmation)
    np_, sh, t, ot = stat(run(by, syms, n, lookback=126, hold=21, frac=0.1, fee=FEE, direction=-1), 21)
    print(f"{'REVERSAL 126/monthly':>26}{np_:>9}{sh:>+8.2f}{t:>+7.2f}{ot:>+7.2f}  (should be negative if momentum is real)")


if __name__ == "__main__":
    main()
