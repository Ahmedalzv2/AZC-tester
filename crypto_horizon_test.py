"""Theory-driven test: does crypto cross-sectional momentum hold at the CLASSIC
horizon (where equities show momentum), or only at the short 14d horizon (where
equities REVERSE)? Pre-registered from the equity replication finding — not a
blind config sweep. If crypto is momentum-positive at the classic horizon too,
the edge is the robust universal factor; if it reverses there like equities, the
14d crypto edge is fragile/short-horizon-specific.
"""
from __future__ import annotations

import json
import math

from mexc_trend_hunt import DATA, hac_t
from cross_sectional_mexc import build_panel

FEE = 0.00075


def run(by, syms, dates, *, lookback, hold, frac=0.1):
    rets, prev = [], {}
    t = lookback
    while t + hold < len(dates):
        dn, dp, df = dates[t], dates[t - lookback], dates[t + hold]
        elig = [(s, by[s][dn] / by[s][dp] - 1) for s in syms
                if dn in by[s] and dp in by[s] and df in by[s] and by[s][dp] > 0]
        if len(elig) < 20:
            t += hold
            continue
        elig.sort(key=lambda x: x[1])
        k = max(1, int(len(elig) * frac))
        win = [s for s, _ in elig[-k:]]
        los = [s for s, _ in elig[:k]]
        w = {s: 0.5 / k for s in win}
        w.update({s: -0.5 / k for s in los})
        gross = sum(w[s] * (by[s][df] / by[s][dn] - 1) for s in w)
        keys = set(w) | set(prev)
        rets.append(gross - sum(abs(w.get(s, 0) - prev.get(s, 0)) for s in keys) * FEE)
        prev = w
        t += hold
    return rets


def main():
    man = {m["symbol"]: m["med_qvol"] for m in json.loads((DATA / "_manifest.json").read_text())}
    dates, by, allsyms = build_panel()
    syms = sorted(allsyms, key=lambda s: -man.get(s, 0))[:100]
    print(f"crypto top-100-liquid, {len(dates)} daily bars\n")
    print(f"{'horizon (lookback/hold days)':>30}{'periods':>9}{'Sharpe':>8}{'HACt':>7}{'OOSt':>7}")
    for lb, hold in [(14, 7), (30, 14), (60, 30), (90, 30), (126, 30)]:
        r = run(by, syms, dates, lookback=lb, hold=hold)
        if len(r) < 5:
            continue
        m = sum(r) / len(r)
        sd = (sum((x - m) ** 2 for x in r) / len(r)) ** 0.5
        sh = m / sd * math.sqrt(365 / hold) if sd else 0.0
        cut = int(len(r) * 0.7)
        print(f"{f'{lb}/{hold}':>30}{len(r):>9}{sh:>+8.2f}{hac_t(r):>+7.2f}{hac_t(r[cut:]):>+7.2f}")


if __name__ == "__main__":
    main()
