"""Diversified vol-targeted trend portfolio — the proven managed-futures edge,
built into an executable, daily-marked portfolio.

The per-trade R-edge (equity-index + commodity trend, t=9 over 100y) becomes a
real return stream only with proper position sizing. Standard managed-futures
construction:
  signal_i  ∈ {-1,0,+1}   Donchian breakout + chandelier-trail direction
  weight_i  = signal_i · (per_asset_vol_target / realized_vol_i)   (inverse-vol)
  port_ret  = Σ weight_i(t-1) · ret_i(t)  −  costs
then one clean scale to the portfolio vol target (no double-targeting, which is
what blew the drawdown out in the first crude pass).

Universe defaults to liquid ETFs (executable at any broker; micro-futures are the
cheaper pro vehicle). Daily data via yahoo period='max'.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

DEFAULT_UNIVERSE = ["SPY", "QQQ", "IWM", "EFA", "EEM", "GLD", "SLV", "DBC", "USO", "TLT"]

# Broadened managed-futures market set (pre-registered, 2026-06-09). Adding
# uncorrelated markets is the documented way to lift a trend portfolio's Sharpe
# (breadth, not knob-tuning). Beat the 10-ETF baseline on every axis and across
# OOS splits: OOS Sharpe 0.68->0.80, OOS t 2.17->2.69 (3.21 @40% split), maxDD
# -24%->-19%, DSR 0.889->0.922 (still <0.95 — better forward candidate, not yet
# fundable; fund on forward t>2). See research/broaden_proven_universe.py.
BROAD_UNIVERSE = [
    "SPY", "QQQ", "IWM", "EFA", "EEM", "EWJ", "VGK",       # equities by region
    "TLT", "IEF", "SHY",                                     # rates
    "GLD", "SLV", "DBC", "USO", "UNG", "DBA", "CPER",        # commodities (all sectors)
    "HYG", "LQD",                                            # credit
    "UUP", "FXE", "FXY",                                     # FX / USD
    "VNQ",                                                   # real assets
]
# The forward candidate config the OOS+deflated search selected on BROAD_UNIVERSE
# (don200/trail5/vt0.10 — longer lookback than the old don100 prod).
FORWARD_PARAMS = {"don": 200, "trail": 5, "vol_target": 0.10, "vol_lookback": 60}


def donchian_trail_position(close, high, low, don=100, atr_n=14, atr_mult=2, trail=5) -> pd.Series:
    """Daily {-1,0,+1} position from Donchian breakout + chandelier trail —
    the same logic the bracket engine validated, as a continuous series."""
    tr = pd.concat([(high - low), (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(atr_n).mean().to_numpy()
    hh = high.rolling(don).max().shift().to_numpy()
    ll = low.rolling(don).min().shift().to_numpy()
    c, h, l = close.to_numpy(), high.to_numpy(), low.to_numpy()
    pos = np.zeros(len(c))
    st: dict | None = None
    for i in range(len(c)):
        if np.isnan(atr[i]) or np.isnan(hh[i]):
            continue
        if st is None:
            d = 1 if c[i] > hh[i] else (-1 if c[i] < ll[i] else 0)
            if d and atr[i] > 0:
                st = {"d": d, "stop": c[i] - atr_mult * atr[i] if d > 0 else c[i] + atr_mult * atr[i],
                      "hwm": c[i], "lwm": c[i], "a": atr[i]}
                pos[i] = d
        else:
            d, td = st["d"], trail * st["a"]
            if d > 0:
                st["hwm"] = max(st["hwm"], h[i]); stop = max(st["stop"], st["hwm"] - td)
                if l[i] <= stop:
                    st = None
                else:
                    pos[i] = 1
            else:
                st["lwm"] = min(st["lwm"], l[i]); stop = min(st["stop"], st["lwm"] + td)
                if h[i] >= stop:
                    st = None
                else:
                    pos[i] = -1
    return pd.Series(pos, index=close.index)


@dataclass(slots=True)
class PortfolioResult:
    daily_returns: pd.Series
    weights: pd.DataFrame
    positions: pd.DataFrame
    metrics: dict[str, Any]


def build_portfolio(ohlc: dict[str, pd.DataFrame], vol_target=0.15, cost_bps=2.0,
                    don=100, trail=5, vol_lookback=60, max_asset_leverage=2.0,
                    max_gross_leverage=4.0) -> PortfolioResult:
    """ohlc: {symbol: DataFrame[Open,High,Low,Close]} (daily). Returns the
    vol-targeted diversified trend portfolio."""
    syms = [s for s, df in ohlc.items() if len(df) > 260]
    closes = pd.DataFrame({s: ohlc[s]["Close"] for s in syms}).sort_index()
    rets = closes.pct_change()
    pos = pd.DataFrame({s: donchian_trail_position(ohlc[s]["Close"], ohlc[s]["High"], ohlc[s]["Low"],
                                                   don=don, trail=trail) for s in syms}).reindex(closes.index).fillna(0)
    # inverse-vol target per asset; spread the portfolio budget over active names
    asset_vol = rets.rolling(vol_lookback).std() * np.sqrt(252)
    active = (pos != 0).sum(axis=1).replace(0, np.nan)
    per_asset_target = (vol_target / np.sqrt(active)).clip(upper=vol_target)
    weight = pos.mul(per_asset_target, axis=0).div(asset_vol.replace(0, np.nan))
    weight = weight.clip(-max_asset_leverage, max_asset_leverage).fillna(0)

    # Raw (relatively-sized) portfolio return, then ONE portfolio-level vol scale
    # to actually hit vol_target — correlations make naive per-asset targeting
    # overshoot when trend is long everything at once. Trailing realized port vol,
    # shifted, so no lookahead. Gross leverage capped for sanity.
    raw_ret = (weight.shift() * rets).sum(axis=1)
    realized = raw_ret.rolling(63).std() * np.sqrt(252)
    port_scale = (vol_target / realized.replace(0, np.nan)).shift().clip(0, max_gross_leverage).fillna(0)
    weight = weight.mul(port_scale, axis=0)

    port = (weight.shift() * rets).sum(axis=1)
    turnover = (weight - weight.shift()).abs().sum(axis=1)
    port = (port - turnover * cost_bps / 10_000).fillna(0)

    metrics = _metrics(port)
    metrics["universe"] = syms
    metrics["recent_5y"] = _metrics(port[port.index >= port.index[-1] - pd.Timedelta(days=5 * 365)])
    return PortfolioResult(daily_returns=port, weights=weight, positions=pos, metrics=metrics)


def _metrics(r: pd.Series) -> dict[str, Any]:
    r = r.dropna()
    if len(r) < 60:
        return {"insufficient": True, "n_days": int(len(r))}
    cagr = float((1 + r).prod() ** (252 / len(r)) - 1)
    vol = float(r.std() * np.sqrt(252))
    eq = (1 + r).cumprod()
    maxdd = float((eq / eq.cummax() - 1).min())
    sharpe = float(cagr / vol) if vol else 0.0
    return {"cagr_pct": round(cagr * 100, 2), "vol_pct": round(vol * 100, 2),
            "sharpe": round(sharpe, 2), "max_dd_pct": round(maxdd * 100, 1),
            "years": round(len(r) / 252, 1)}


def current_targets(ohlc: dict[str, pd.DataFrame], **kw) -> dict[str, float]:
    """Today's target weights (the last row) — what the paper lane should hold."""
    res = build_portfolio(ohlc, **kw)
    last = res.weights.iloc[-1]
    return {s: round(float(w), 4) for s, w in last.items() if abs(w) > 1e-4}
