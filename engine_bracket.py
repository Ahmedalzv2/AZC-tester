"""Faithful bracket/stop execution engine — the AZC lane.

The default backtest engine (engine.py) is a long-only, mark-to-close,
fractional-position model. The AZC crypto strategies are different animals:
they enter on the NEXT bar's open after a 4h Donchian signal, exit intrabar at
an ATR stop / fixed-RR target (or a chandelier trail), size by risk-per-trade,
and pay MEXC taker/maker fees per leg. Shoe-horning them into the close-to-close
engine prints a number that does not match reality — the exact mistake that
killed the live lane. So they get their own execution path here.

This is a line-for-line port of `simulateMeanRev` in the AZC repo
(ict-autopilot/tests/backtest-meanrev.mjs). The parity test
(tests/test_bracket_parity.py) asserts it reproduces the JS engine's metrics
on the shared fixtures, so the two cannot silently diverge.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ATR_N_DEFAULT = 14


@dataclass(slots=True)
class Bar:
    t: int
    o: float
    h: float
    l: float
    c: float


def to_bars(df) -> list[Bar]:
    """OHLCV DataFrame (DatetimeIndex) -> AZC bar list. Timestamp is epoch ms."""
    bars: list[Bar] = []
    for idx, row in df.iterrows():
        ts = int(idx.value // 1_000_000)  # ns -> ms
        bars.append(Bar(ts, float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])))
    return bars


def resample_positional(bars: list[Bar], per: int) -> list[Bar]:
    """Non-overlapping positional aggregation, matching AZC `resample()`.

    Groups by index position from the start of the array (NOT wall-clock
    boundaries) so it reproduces the JS engine bar-for-bar."""
    out: list[Bar] = []
    i = 0
    n = len(bars)
    while i + per <= n:
        s = bars[i : i + per]
        out.append(
            Bar(
                t=s[0].t,
                o=s[0].o,
                h=max(x.h for x in s),
                l=min(x.l for x in s),
                c=s[-1].c,
            )
        )
        i += per
    return out


def atr(bars: list[Bar], i: int, n: int = ATR_N_DEFAULT) -> float:
    total = 0.0
    for k in range(i - n + 1, i + 1):
        total += max(
            bars[k].h - bars[k].l,
            abs(bars[k].h - bars[k - 1].c),
            abs(bars[k].l - bars[k - 1].c),
        )
    return total / n


def efficiency_ratio(bars: list[Bar], i: int, n: int) -> float:
    """Kaufman efficiency ratio over the last n bars — the trend regime gate."""
    if i - n < 0:
        return 0.0
    net = abs(bars[i].c - bars[i - n].c)
    vol = 0.0
    for k in range(i - n + 1, i + 1):
        vol += abs(bars[k].c - bars[k - 1].c)
    return net / vol if vol > 0 else 0.0


def simulate_bracket(bars: list[Bar], p: dict[str, Any], from_idx: int | None = None, to: int | None = None) -> list[dict[str, Any]]:
    """Port of simulateMeanRev (ict-autopilot/tests/backtest-meanrev.mjs).

    fade=True  -> mean-reversion: fade the Donchian extreme.
    fade=False -> trend: break the Donchian channel in the trend direction.
    trail>0    -> chandelier trailing stop (always a taker exit).
    erMin>0    -> regime gate (trend only): skip entries when efficiency ratio
                  below erMin (chop). The live trend lane runs this gate; the
                  raw simulateMeanRev does not, so it is opt-in via params.
    """
    don = int(p["don"])
    atr_mult = float(p["atrMult"])
    rr = float(p.get("rr", 1.2))
    atr_n = int(p.get("atrN", ATR_N_DEFAULT))
    fade = p.get("fade", True) is not False
    trail = float(p.get("trail", 0) or 0)
    maker_entry = bool(p.get("makerEntry", True))
    maker_tp = bool(p.get("makerTp", True))
    taker_rate = float(p.get("takerRate", 0.00075))
    slip = float(p.get("slipBps", 0)) / 10000.0
    regime_n = int(p.get("regimeN", 20))
    er_min = float(p.get("erMin", 0) or 0)

    n = len(bars)
    to = n if to is None else to
    from_idx = atr_n + 1 if from_idx is None else from_idx

    trades: list[dict[str, Any]] = []
    i = max(from_idx, don + 1, atr_n + 1)
    while i < to - 1:
        b = bars[i]
        hh = max(x.h for x in bars[i - don : i])
        ll = min(x.l for x in bars[i - don : i])
        a = atr(bars, i, atr_n)
        direction = None
        if b.c > hh:
            direction = "short" if fade else "long"
        elif b.c < ll:
            direction = "long" if fade else "short"

        # Trend regime gate: stand aside in chop (opt-in via erMin).
        if direction and er_min > 0 and not fade and efficiency_ratio(bars, i, regime_n) < er_min:
            direction = None

        if direction and a > 0 and i + 1 < to:
            entry = bars[i + 1].o  # next-open entry, no lookahead
            risk = atr_mult * a
            stop = entry - risk if direction == "long" else entry + risk
            tp = entry + rr * risk if direction == "long" else entry - rr * risk
            exit_idx, exit_px, win, taker_exit = -1, None, False, True

            if trail > 0:
                trail_dist = trail * a
                hwm, lwm = entry, entry
                j = i + 1
                while j < to:
                    x = bars[j]
                    if direction == "long":
                        cur = max(stop, hwm - trail_dist)
                        if x.l <= cur:
                            exit_px, exit_idx = cur, j
                            break
                        hwm = max(hwm, x.h)  # update after stop check — no lookahead
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
                while j < to:
                    x = bars[j]
                    hit_stop = x.l <= stop if direction == "long" else x.h >= stop
                    hit_tp = x.h >= tp if direction == "long" else x.l <= tp
                    if hit_stop:  # stop first on ties (pessimistic)
                        exit_px, win, exit_idx = stop, False, j
                        break
                    if hit_tp:
                        exit_px, win, exit_idx = tp, True, j
                        break
                    j += 1
                taker_exit = not win  # TP win fills maker, SL loss taker

            if exit_idx >= 0:
                sgn = 1 if direction == "long" else -1
                entry_fill = entry if maker_entry else entry * (1 + sgn * slip)
                exit_fill = exit_px * (1 - sgn * slip) if taker_exit else exit_px
                move = exit_fill - entry_fill if direction == "long" else entry_fill - exit_fill
                gross_r = move / risk
                entry_fee = 0.0 if maker_entry else taker_rate
                exit_fee = taker_rate if taker_exit else (0.0 if maker_tp else taker_rate)
                fee_r = (entry * (entry_fee + exit_fee)) / risk
                trades.append(
                    {
                        "ts": b.t,
                        "entry_idx": i + 1,
                        "exit_idx": exit_idx,
                        "dir": direction,
                        "entry": entry,
                        "exit": exit_px,
                        "grossR": gross_r,
                        "netR": gross_r - fee_r,
                        "win": win,
                    }
                )
                i = exit_idx
        i += 1
    return trades


_INTERVAL_MS = {
    "5m": 5 * 60_000, "15m": 15 * 60_000, "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000, "1d": 24 * 60 * 60_000,
}


_FOUR_H_MS = 4 * 60 * 60 * 1000


def _infer_4h_per(bars: list[Bar]) -> int:
    """How many base bars aggregate to 4h, from the data's own spacing.

    Robust to whatever interval the user loaded (5m/15m/1h all map to 4h);
    coarser-than-4h data (e.g. daily) clamps to 1 = no resample."""
    if len(bars) < 3:
        return 1
    deltas = sorted(bars[k + 1].t - bars[k].t for k in range(len(bars) - 1))
    median = deltas[len(deltas) // 2]
    if median <= 0:
        return 1
    return max(1, round(_FOUR_H_MS / median))


def run_bracket_backtest(df, params, initial_cash, interval, resample_per=None):
    """Frontend-shaped result for an AZC bracket strategy.

    R-native truth (netR/trade, totalR) drives a compounded cash curve at
    `riskPct` per trade, so the equity line and the R metrics agree. Returns the
    same metric keys the close-to-close engine does, plus R-native fields.

    The base series is aggregated to 4h positionally (matching AZC) — the factor
    is auto-detected from the data's bar spacing unless `resample_per` forces it.
    """
    bars = to_bars(df)
    per = resample_per if (resample_per and resample_per > 1) else _infer_4h_per(bars)
    if per > 1:
        bars = resample_positional(bars, per)
    if len(bars) < int(params.get("don", 30)) + 2:
        raise ValueError("Not enough bars for the chosen Donchian lookback")

    trades = simulate_bracket(bars, params)
    m = bracket_metrics(trades)
    risk_pct = float(params.get("riskPct", 0.005))

    # Compounded cash curve: each closed trade moves equity by netR * riskPct.
    by_exit = {t["exit_idx"]: t for t in trades}
    open_dir = [0.0] * len(bars)
    for t in trades:
        sign = 1.0 if t["dir"] == "long" else -1.0
        for k in range(t["entry_idx"], min(t["exit_idx"] + 1, len(bars))):
            open_dir[k] = sign

    equity = initial_cash
    peak = initial_cash
    max_dd = 0.0
    curve = []
    for idx, bar in enumerate(bars):
        if idx in by_exit:
            equity *= 1 + by_exit[idx]["netR"] * risk_pct
        if equity > peak:
            peak = equity
        dd = equity / peak - 1 if peak else 0.0
        if dd < max_dd:
            max_dd = dd
        curve.append({
            "time": _ms_iso(bar.t),
            "close": round(bar.c, 6),
            "equity": round(equity, 2),
            "position": open_dir[idx],
            "drawdown": round(dd * 100, 3),
        })

    span_ms = max(bars[-1].t - bars[0].t, 1)
    years = span_ms / (365.25 * 24 * 3600 * 1000)
    total_return = equity / initial_cash - 1
    annualized = (equity / initial_cash) ** (1 / years) - 1 if years > 0 and equity > 0 else 0.0

    # Annualized Sharpe on the per-trade netR series (cash-equivalent).
    net_rs = [t["netR"] * risk_pct for t in trades]
    sharpe = 0.0
    if len(net_rs) > 1:
        mean = sum(net_rs) / len(net_rs)
        var = sum((x - mean) ** 2 for x in net_rs) / len(net_rs)
        sd = var ** 0.5
        if sd > 0 and years > 0:
            sharpe = (mean / sd) * (len(net_rs) / years) ** 0.5

    maker_entry = bool(params.get("makerEntry", True))
    maker_tp = bool(params.get("makerTp", True))
    fee_model = "all-taker" if not (maker_entry or maker_tp) else (
        "maker entry+TP / taker stop" if maker_entry and maker_tp else "mixed maker/taker")

    metrics = {
        "ending_equity": round(equity, 2),
        "total_return_pct": round(total_return * 100, 3),
        "annualized_return_pct": round(annualized * 100, 3),
        "max_drawdown_pct": round(max_dd * 100, 3),
        "sharpe": round(sharpe, 3),
        "trade_count": m["n"],
        "win_rate_pct": round(m["winPct"], 3),
        "exposure_pct": round(sum(1 for d in open_dir if d != 0) / max(len(bars), 1) * 100, 3),
        # R-native truth — the numbers the AZC research is judged on.
        "net_r_per_trade": round(m["netR"], 4),
        "total_r": round(m["totalR"], 3),
        "max_drawdown_r": round(m["maxDD"], 3),
        "fee_model": fee_model,
        "risk_pct": risk_pct,
        "bars_4h": len(bars),
        "strategy_params": {k: v for k, v in params.items()},
        "interval": interval,
        "execution": "bracket",
    }

    trade_rows = [
        {
            "entry_at": _ms_iso(bars[t["entry_idx"]].t),
            "exit_at": _ms_iso(bars[t["exit_idx"]].t),
            "entry_price": round(t["entry"], 6),
            "exit_price": round(t["exit"], 6),
            "pnl_pct": round(t["netR"], 3),  # R, not %, for bracket trades
            "equity_after": None,
        }
        for t in trades[-200:]
    ]
    return metrics, curve, trade_rows


def _ms_iso(ms: int) -> str:
    import datetime as _dt
    return _dt.datetime.fromtimestamp(ms / 1000, tz=_dt.timezone.utc).isoformat()


def bracket_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """R-native metrics, matching AZC `metrics()` (equal-weight per trade)."""
    n = len(trades)
    if not n:
        return {"n": 0, "winPct": 0.0, "netR": 0.0, "totalR": 0.0, "maxDD": 0.0}
    eq = peak = max_dd = total_r = 0.0
    wins = 0
    for t in trades:
        total_r += t["netR"]
        eq += t["netR"]
        if eq > peak:
            peak = eq
        if peak - eq > max_dd:
            max_dd = peak - eq
        if t["win"]:
            wins += 1
    return {"n": n, "winPct": wins / n * 100, "netR": total_r / n, "totalR": total_r, "maxDD": max_dd}
