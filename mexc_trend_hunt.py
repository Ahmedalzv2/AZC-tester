"""Standalone fee-accurate daily trend backtester for the full MEXC perp universe.

Deliberately self-contained: it does NOT import the shared bracket engine (which
has uncommitted WIP in the working tree), so results never depend on someone
else's unstaged edits. Parity with the prod azc_trend logic is by construction —
same Donchian breakout + ATR stop + chandelier trail + efficiency-ratio gate.

Discipline baked in (playbook hard rules):
  * decisions use only closed past bars; fills at the NEXT bar open  -> no lookahead
  * fees charged per leg on both entry and exit                     -> honest costs
  * per-trade netR series -> Newey-West (HAC) t-stat                -> real vs noise
  * 70/30 in-sample/out-of-sample split, judged on OOS              -> no IS mirage
  * Bonferroni across the universe is applied by the caller          -> multiple-testing
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data_cache" / "mexc"


@dataclass
class Bar:
    ts: int
    o: float
    h: float
    l: float
    c: float


def load(symbol: str) -> list[Bar]:
    out = []
    with (DATA / f"{symbol}.csv").open() as f:
        r = csv.DictReader(f)
        for row in r:
            out.append(Bar(int(row["ts"]), float(row["open"]), float(row["high"]),
                           float(row["low"]), float(row["close"])))
    return out


def atr(bars: list[Bar], n: int) -> list[float]:
    """Wilder ATR; atr[i] uses bars up to and including i."""
    tr = [bars[0].h - bars[0].l]
    for i in range(1, len(bars)):
        h, l, pc = bars[i].h, bars[i].l, bars[i - 1].c
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    out = [float("nan")] * len(bars)
    if len(bars) < n:
        return out
    a = sum(tr[:n]) / n
    out[n - 1] = a
    for i in range(n, len(bars)):
        a = (a * (n - 1) + tr[i]) / n
        out[i] = a
    return out


def eff_ratio(bars: list[Bar], i: int, n: int) -> float:
    """Kaufman efficiency ratio over the last n closes ending at i (inclusive)."""
    if i < n:
        return 0.0
    net = abs(bars[i].c - bars[i - n].c)
    vol = sum(abs(bars[k].c - bars[k - 1].c) for k in range(i - n + 1, i + 1))
    return net / vol if vol > 0 else 0.0


@dataclass
class Params:
    don: int = 30
    atr_n: int = 14
    atr_mult: float = 3.0
    trail: float = 5.0
    er_min: float = 0.35
    regime_n: int = 20


def signals(bars: list[Bar], p: Params) -> list[tuple[int, int]]:
    """Return (decision_bar_index, side) using ONLY bars[0..i]. side: +1 long, -1 short.

    A breakout is a close beyond the prior `don`-bar channel, with the regime gate
    open. The fill happens at bars[i+1].open (handled by the simulator).
    """
    a = atr(bars, p.atr_n)
    sig = []
    start = max(p.don, p.atr_n, p.regime_n) + 1
    for i in range(start, len(bars) - 1):  # -1: need a next bar to fill on
        if math.isnan(a[i]):
            continue
        if eff_ratio(bars, i, p.regime_n) < p.er_min:
            continue
        prior_hi = max(b.h for b in bars[i - p.don:i])
        prior_lo = min(b.l for b in bars[i - p.don:i])
        if bars[i].c > prior_hi:
            sig.append((i, +1))
        elif bars[i].c < prior_lo:
            sig.append((i, -1))
    return sig


def backtest(bars: list[Bar], p: Params, fee: float) -> list[float]:
    """Walk the tape, one position at a time, return the per-trade netR series."""
    a = atr(bars, p.atr_n)
    rs: list[float] = []
    sig = dict(signals(bars, p))
    i = 0
    n = len(bars)
    while i < n - 1:
        if i not in sig:
            i += 1
            continue
        side = sig[i]
        entry_i = i + 1
        entry = bars[entry_i].o
        risk = p.atr_mult * a[i]
        if risk <= 0 or entry <= 0:
            i = entry_i
            continue
        if side > 0:
            stop = entry - risk
            extreme = bars[entry_i].h
        else:
            stop = entry + risk
            extreme = bars[entry_i].l
        exit_price = None
        j = entry_i
        while j < n:
            b = bars[j]
            if side > 0:
                extreme = max(extreme, b.h)
                stop = max(stop, extreme - p.trail * a[j] if not math.isnan(a[j]) else stop)
                if b.l <= stop:
                    exit_price = min(stop, b.o) if b.o < stop else stop
                    break
            else:
                extreme = min(extreme, b.l)
                trail_stop = extreme + p.trail * a[j] if not math.isnan(a[j]) else stop
                stop = min(stop, trail_stop)
                if b.h >= stop:
                    exit_price = max(stop, b.o) if b.o > stop else stop
                    break
            j += 1
        if exit_price is None:  # still open at tape end -> mark to last close
            exit_price = bars[-1].c
            j = n - 1
        gross = (exit_price - entry) / entry if side > 0 else (entry - exit_price) / entry
        net = gross - 2 * fee
        rs.append(net / (risk / entry))  # netR in initial-risk units
        i = j + 1  # no overlapping positions
    return rs


def backtest_fade(bars: list[Bar], p: Params, fee: float) -> list[float]:
    """Real mean-reversion: fade a Donchian breakout, exit on reversion to the
    channel midline (take-profit) or an ATR stop the wrong way. Fees charged on
    BOTH legs (unlike a naive sign-flip of the trend series). One position at a time.

    Entry at bars[i+1].open after a close beyond the prior `don`-bar channel:
      close < prior low  -> LONG (fade the breakdown)
      close > prior high -> SHORT (fade the breakout)
    """
    a = atr(bars, p.atr_n)
    rs: list[float] = []
    n = len(bars)
    start = max(p.don, p.atr_n, p.regime_n) + 1
    i = start
    while i < n - 1:
        if math.isnan(a[i]):
            i += 1
            continue
        if eff_ratio(bars, i, p.regime_n) >= p.er_min:
            # fade wants chop, not a clean trend; skip strong-trend regimes
            i += 1
            continue
        prior_hi = max(b.h for b in bars[i - p.don:i])
        prior_lo = min(b.l for b in bars[i - p.don:i])
        mid = 0.5 * (prior_hi + prior_lo)
        side = 0
        if bars[i].c < prior_lo:
            side = +1
        elif bars[i].c > prior_hi:
            side = -1
        if side == 0:
            i += 1
            continue
        entry_i = i + 1
        entry = bars[entry_i].o
        risk = p.atr_mult * a[i]
        if risk <= 0 or entry <= 0:
            i = entry_i
            continue
        stop = entry - risk if side > 0 else entry + risk
        target = mid  # revert to channel midline
        exit_price = None
        j = entry_i
        while j < n:
            b = bars[j]
            if side > 0:
                if b.l <= stop:
                    exit_price = min(stop, b.o)
                    break
                if b.h >= target:
                    exit_price = max(target, b.o)
                    break
            else:
                if b.h >= stop:
                    exit_price = max(stop, b.o)
                    break
                if b.l <= target:
                    exit_price = min(target, b.o)
                    break
            j += 1
        if exit_price is None:
            exit_price = bars[-1].c
            j = n - 1
        gross = (exit_price - entry) / entry if side > 0 else (entry - exit_price) / entry
        net = gross - 2 * fee
        rs.append(net / (risk / entry))
        i = j + 1
    return rs


def hac_t(x: list[float], lags: int | None = None) -> float:
    """Newey-West t-stat of the mean (HAC, Bartlett kernel)."""
    n = len(x)
    if n < 5:
        return 0.0
    m = sum(x) / n
    d = [v - m for v in x]
    g0 = sum(v * v for v in d) / n
    if g0 == 0:
        return 0.0
    L = lags if lags is not None else int(round(4 * (n / 100) ** (2 / 9)))
    var = g0
    for k in range(1, L + 1):
        gk = sum(d[t] * d[t - k] for t in range(k, n)) / n
        var += 2 * (1 - k / (L + 1)) * gk
    se = math.sqrt(max(var, 1e-12) / n)
    return m / se


def evaluate(bars: list[Bar], p: Params, fee: float) -> dict:
    """Full-sample + 70/30 OOS split metrics on the per-trade netR series."""
    rs = backtest(bars, p, fee)
    if not rs:
        return {"n": 0, "netR": 0.0, "t": 0.0, "oos_n": 0, "oos_netR": 0.0, "oos_t": 0.0, "total_R": 0.0}
    cut = int(len(rs) * 0.7)
    oos = rs[cut:]
    return {
        "n": len(rs),
        "netR": sum(rs) / len(rs),
        "t": hac_t(rs),
        "total_R": sum(rs),
        "oos_n": len(oos),
        "oos_netR": (sum(oos) / len(oos)) if oos else 0.0,
        "oos_t": hac_t(oos),
    }
