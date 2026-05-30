"""Generic bracket simulator + a library of entry-signal families.

The validated `engine_bracket.simulate_bracket` hard-codes one entry rule
(Donchian break/fade). To honestly *search* for an edge we need to try many
entry signals through the SAME fee-accurate bracket exit machinery. This module
provides:

- `simulate_signal(bars, entry_fn, params)` — the bracket exit/fee lifecycle
  (next-open entry, ATR stop, fixed-RR target or chandelier trail, per-leg
  maker/taker fees, one position at a time), with a pluggable entry function.
- a library of entry signals, each `fn(bars, i, params) -> "long"|"short"|None`
  evaluated on the just-closed bar i (no lookahead).

A parity test asserts `simulate_signal(donchian_break/fade)` reproduces the
canonical `simulate_bracket`, so the shared exit logic cannot silently drift.
"""
from __future__ import annotations

import math
from typing import Any, Callable

from engine_bracket import Bar, atr, efficiency_ratio

EntryFn = Callable[[list[Bar], int, dict[str, Any]], str | None]


# ── entry-signal library ────────────────────────────────────────────────────
def _hh_ll(bars, i, n):
    return max(x.h for x in bars[i - n:i]), min(x.l for x in bars[i - n:i])


def donchian_break(bars, i, p):  # trend / continuation
    don = int(p["don"])
    hh, ll = _hh_ll(bars, i, don)
    if bars[i].c > hh:
        return "long"
    if bars[i].c < ll:
        return "short"
    return None


def donchian_fade(bars, i, p):  # mean reversion
    d = donchian_break(bars, i, p)
    return {"long": "short", "short": "long"}.get(d)


def ts_momentum(bars, i, p):  # time-series momentum
    look = int(p["mom"])
    if i - look < 0:
        return None
    ret = bars[i].c / bars[i - look].c - 1
    thr = float(p.get("mom_thr", 0.0))
    if ret > thr:
        return "long"
    if ret < -thr:
        return "short"
    return None


def _sma(bars, i, n):
    return sum(bars[k].c for k in range(i - n + 1, i + 1)) / n


def ma_cross(bars, i, p):
    fast, slow = int(p["fast"]), int(p["slow"])
    if i - slow < 0:
        return None
    return "long" if _sma(bars, i, fast) > _sma(bars, i, slow) else "short"


def _rsi(bars, i, n):
    gains = losses = 0.0
    for k in range(i - n + 1, i + 1):
        ch = bars[k].c - bars[k - 1].c
        if ch >= 0:
            gains += ch
        else:
            losses -= ch
    if losses == 0:
        return 100.0
    rs = (gains / n) / (losses / n)
    return 100 - 100 / (1 + rs)


def rsi_reversion(bars, i, p):
    n = int(p.get("rsi_n", 14))
    if i - n < 0:
        return None
    r = _rsi(bars, i, n)
    if r < float(p.get("lower", 30)):
        return "long"
    if r > float(p.get("upper", 70)):
        return "short"
    return None


def _mean_std(bars, i, n):
    xs = [bars[k].c for k in range(i - n + 1, i + 1)]
    m = sum(xs) / n
    var = sum((x - m) ** 2 for x in xs) / n
    return m, math.sqrt(var)


def bollinger_break(bars, i, p):
    n = int(p.get("bb_n", 20))
    k = float(p.get("bb_k", 2))
    if i - n < 0:
        return None
    m, sd = _mean_std(bars, i, n)
    if bars[i].c > m + k * sd:
        return "long"
    if bars[i].c < m - k * sd:
        return "short"
    return None


def bollinger_fade(bars, i, p):
    d = bollinger_break(bars, i, p)
    return {"long": "short", "short": "long"}.get(d)


SIGNALS: dict[str, EntryFn] = {
    "donchian_break": donchian_break,
    "donchian_fade": donchian_fade,
    "ts_momentum": ts_momentum,
    "ma_cross": ma_cross,
    "rsi_reversion": rsi_reversion,
    "bollinger_break": bollinger_break,
    "bollinger_fade": bollinger_fade,
}


def _warmup(p: dict[str, Any]) -> int:
    """Bars of history any signal/ATR could need before the first decision."""
    # +1 to match simulate_bracket's first index = max(don, atrN) + 1, so the
    # generic donchian path is bar-for-bar identical to the canonical engine.
    return max(
        int(p.get("don", 0)), int(p.get("slow", 0)), int(p.get("mom", 0)),
        int(p.get("rsi_n", 0)), int(p.get("bb_n", 0)), int(p.get("atrN", 14)),
    ) + 1


# ── generic bracket simulator (exit/fee machinery mirrors simulate_bracket) ──
def simulate_signal(bars: list[Bar], entry_fn: EntryFn, p: dict[str, Any]) -> list[dict[str, Any]]:
    atr_mult = float(p["atrMult"])
    rr = float(p.get("rr", 1.2))
    atr_n = int(p.get("atrN", 14))
    trail = float(p.get("trail", 0) or 0)
    maker_entry = bool(p.get("makerEntry", True))
    maker_tp = bool(p.get("makerTp", True))
    taker_rate = float(p.get("takerRate", 0.00075))
    slip = float(p.get("slipBps", 0)) / 10000.0
    er_min = float(p.get("erMin", 0) or 0)
    regime_n = int(p.get("regimeN", 20))

    n = len(bars)
    trades: list[dict[str, Any]] = []
    i = max(_warmup(p), atr_n + 1)
    while i < n - 1:
        direction = entry_fn(bars, i, p)
        a = atr(bars, i, atr_n)
        # Optional regime gate (any directional signal): trade only in trend.
        if direction and er_min > 0 and efficiency_ratio(bars, i, regime_n) < er_min:
            direction = None
        if direction and a > 0:
            entry = bars[i + 1].o
            risk = atr_mult * a
            stop = entry - risk if direction == "long" else entry + risk
            tp = entry + rr * risk if direction == "long" else entry - rr * risk
            exit_idx, exit_px, win, taker_exit = -1, None, False, True
            if trail > 0:
                trail_dist = trail * a
                hwm, lwm, j = entry, entry, i + 1
                while j < n:
                    x = bars[j]
                    if direction == "long":
                        cur = max(stop, hwm - trail_dist)
                        if x.l <= cur:
                            exit_px, exit_idx = cur, j
                            break
                        hwm = max(hwm, x.h)
                    else:
                        cur = min(stop, lwm + trail_dist)
                        if x.h >= cur:
                            exit_px, exit_idx = cur, j
                            break
                        lwm = min(lwm, x.l)
                    j += 1
                if exit_idx >= 0:
                    win = exit_px > entry if direction == "long" else exit_px < entry
            else:
                j = i + 1
                while j < n:
                    x = bars[j]
                    hit_stop = x.l <= stop if direction == "long" else x.h >= stop
                    hit_tp = x.h >= tp if direction == "long" else x.l <= tp
                    if hit_stop:
                        exit_px, win, exit_idx = stop, False, j
                        break
                    if hit_tp:
                        exit_px, win, exit_idx = tp, True, j
                        break
                    j += 1
                taker_exit = not win
            if exit_idx >= 0:
                sgn = 1 if direction == "long" else -1
                entry_fill = entry if maker_entry else entry * (1 + sgn * slip)
                exit_fill = exit_px * (1 - sgn * slip) if taker_exit else exit_px
                move = exit_fill - entry_fill if direction == "long" else entry_fill - exit_fill
                gross_r = move / risk
                entry_fee = 0.0 if maker_entry else taker_rate
                exit_fee = taker_rate if taker_exit else (0.0 if maker_tp else taker_rate)
                fee_r = (entry * (entry_fee + exit_fee)) / risk
                trades.append({"ts": bars[i].t, "dir": direction, "netR": gross_r - fee_r, "win": win})
                i = exit_idx
        i += 1
    return trades
