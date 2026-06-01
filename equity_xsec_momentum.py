"""Long-horizon cross-sectional momentum on liquid US large-caps — the factor that
ACTUALLY replicated externally (Jegadeesh-Titman, 60-252d, decades of equity
evidence; our equity_crosssec_replication.py got 126d t=2.31, reversal t=-2.54).

Distinct from the existing ETF *trend* lane (time-series momentum). This ranks the
cross-section: each month, sort names by their trailing ~6-month return, hold the
top decile (long) and optionally short the bottom decile.

Honesty notes:
  * decisions use closes <= t, returns realised t->t+hold (bar counts, no lookahead);
  * SURVIVORSHIP: the universe is today's liquid large-caps (yfinance), which is
    survivorship-biased — it inflates the SHORT/losers leg. So the headline we trust
    is LONG-ONLY EXCESS over the equal-weight universe (survivorship-robust on the
    long side), and it's the tradeable form (no borrow). L/S is reported too, flagged.
  * fees ~ a few bps; equities are cheap vs crypto, but we keep costs in.
"""
from __future__ import annotations

import math

import yfinance as yf

from mexc_trend_hunt import hac_t

# ~150 liquid US large-caps (deep, long-listed). Survivorship-biased by construction.
TICKERS = (
    "AAPL MSFT AMZN GOOGL GOOG META NVDA TSLA JPM V JNJ WMT PG MA HD BAC XOM DIS KO PEP "
    "CSCO INTC VZ ADBE CRM NFLX CMCSA PFE ABT TMO NKE MRK ORCL ACN COST AVGO TXN QCOM HON "
    "UNH LLY CVX WFC MCD MDT NEE PM LOW UPS MS GS BLK CAT BA AXP GE MMM IBM AMGN SBUX GILD "
    "MDLZ ISRG NOW INTU AMD BKNG ADP LRCX MU ZTS PYPL REGN VRTX PANW KLAC SNPS CDNS FTNT "
    "C USB PNC TGT DUK SO D AEP CL KMB GIS K HSY SYK BDX BSX EW ZBH DHR A LIN APD SHW ECL "
    "FCX NEM NUE DOW EMR ETN ITW PH ROK DE CMI FDX NSC UNP CSX LMT NOC GD RTX EOG SLB MPC "
    "PSX VLO OXY WMB KMI HCA CI CVS ELV HUM MO COP DVN HAL BKR APA TJX ROST DG DLTR YUM "
    "CMG MAR HLT EBAY ETSY ADI MCHP NXPI AMAT WDAY TEAM DDOG NET CRWD ZS"
).split()
FEE = 0.0005  # ~5bp round-trip


def fetch_panel(tickers=TICKERS, years=14):
    df = yf.download(list(tickers), period=f"{years}y", interval="1d",
                     auto_adjust=True, progress=False, threads=True)["Close"]
    df = df.dropna(axis=1, thresh=int(len(df) * 0.85))
    dates = list(df.index)
    by = {c: {i: float(v) for i, v in enumerate(df[c].tolist()) if v == v} for c in df.columns}
    return dates, by, list(df.columns)


def walk(by, syms, n, *, lookback, hold, frac, fee, mode="long_short", skip=0):
    """mode: 'long_short' (decile L/S, dollar-neutral) or 'long_excess'
    (top-decile long minus equal-weight universe = survivorship-robust, tradeable).
    skip: bars to skip between the formation window and now (canonical 12-1 momentum
    skips ~21 bars so short-term REVERSAL in the most recent month doesn't contaminate
    the momentum signal). Signal = return from t-lookback to t-skip."""
    rets, prev = [], {}
    t = lookback
    while t + hold < n:
        s_end = t - skip  # signal measured up to here, skipping the recent `skip` bars
        elig = [(s, by[s][s_end] / by[s][t - lookback] - 1) for s in syms
                if s_end in by[s] and t - lookback in by[s] and t in by[s] and t + hold in by[s]
                and by[s][t - lookback] > 0]
        if len(elig) < 20:
            t += hold
            continue
        elig.sort(key=lambda x: x[1])
        k = max(1, int(len(elig) * frac))
        win = [s for s, _ in elig[-k:]]
        los = [s for s, _ in elig[:k]]
        if mode == "long_short":
            w = {s: 0.5 / k for s in win}
            w.update({s: -0.5 / k for s in los})
            gross = sum(w[s] * (by[s][t + hold] / by[s][t] - 1) for s in w)
        else:  # long_excess
            w = {s: 1.0 / k for s in win}
            long_ret = sum(w[s] * (by[s][t + hold] / by[s][t] - 1) for s in w)
            mkt = sum(by[s][t + hold] / by[s][t] - 1 for s, _ in elig) / len(elig)
            gross = long_ret - mkt
        keys = set(w) | set(prev)
        rets.append(gross - sum(abs(w.get(s, 0) - prev.get(s, 0)) for s in keys) * fee)
        prev = w
        t += hold
    return rets


def stats(rets, hold):
    if len(rets) < 5:
        return {"n": len(rets), "sharpe": 0.0, "t": 0.0, "oos_t": 0.0, "mean_pct": 0.0}
    m = sum(rets) / len(rets)
    sd = (sum((x - m) ** 2 for x in rets) / len(rets)) ** 0.5
    cut = int(len(rets) * 0.7)
    return {"n": len(rets), "sharpe": round(m / sd * math.sqrt(252 / hold), 2) if sd else 0.0,
            "t": round(hac_t(rets), 2), "oos_t": round(hac_t(rets[cut:]), 2),
            "mean_pct": round(m * 100, 3)}


# LOCKED config: canonical 12-1 cross-sectional momentum (252d formation, skip the
# most recent 21d to avoid short-term reversal), monthly hold, top decile, LONG-ONLY.
LOCKED = {"lookback": 252, "skip": 21, "hold": 21, "frac": 0.10, "mode": "long_excess"}


def main():
    dates, by, syms = fetch_panel()
    n = len(dates)
    print(f"equity panel: {len(syms)} liquid large-caps, {n} bars "
          f"({dates[0].date()}..{dates[-1].date()})\n")
    s = stats(walk(by, syms, n, fee=FEE, **LOCKED), LOCKED["hold"])
    print(f"LOCKED 12-1 long-only top-decile (excess over eq-wt market):")
    print(f"  periods={s['n']} Sharpe={s['sharpe']:+.2f} HACt={s['t']:+.2f} "
          f"OOSt={s['oos_t']:+.2f} mean={s['mean_pct']:+.3f}%/mo")


if __name__ == "__main__":
    main()
