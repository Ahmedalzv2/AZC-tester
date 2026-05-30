"""Alpha Zoo — published quant factors as causal single-asset signals.

Most "alpha zoos" (Kakushadze Alpha101 arXiv:1601.00991; Guotai-Junan gtja191;
academic factors) are *cross-sectional*: at each timestamp they rank a metric
ACROSS a universe of stocks. On one asset's time series a cross-sectional rank
is degenerate (the rank of a single item is always 1), so blindly "porting 101
factors" to a single symbol is fake science.

The honest move, and what this module does:
  1. Keep only factors whose core idea is a single-asset TIME-SERIES signal
     (momentum, reversal, vol, volume confirmation, intraday position).
  2. Replace any cross-sectional rank() with a CAUSAL rolling z-score over the
     asset's own history (expanding/rolling, never the full sample).
  3. Squash to a position in [-1, 1] with tanh, so the engine can trade it.

Every factor here is causal: signal at bar t uses only bars <= t. The test
suite enforces this with a lookahead sentinel (perturbing future bars must not
change past signals). This is a curated, pre-registered hypothesis set — not a
blind grid — so testing it under cumulative Bonferroni is legitimate research.

Provenance is recorded per factor. We port FORMULAS (ideas), which are facts,
not copyrightable code; original Alpha101 is from the paper, gtja191 from the
2014 Guotai-Junan report. Vibe-Trading (MIT) is the inspiration to assemble a
zoo + lookahead sentinel, not a code source.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

SignalFn = Callable[[pd.DataFrame], pd.Series]

# Rolling window for the causal z-score that stands in for cross-sectional rank.
_Z_WIN = 60


def _causal_z(x: pd.Series, win: int = _Z_WIN) -> pd.Series:
    """Causal rolling z-score. Uses only the trailing `win` bars, so it can
    never see the future. Replaces the cross-sectional rank() in the originals.
    """
    mean = x.rolling(win, min_periods=max(5, win // 4)).mean()
    std = x.rolling(win, min_periods=max(5, win // 4)).std(ddof=0)
    z = (x - mean) / std.replace(0.0, np.nan)
    return z


def _to_position(raw: pd.Series, index: pd.Index) -> pd.Series:
    """Squash any real-valued signal to a bounded [-1, 1] position, causally."""
    s = pd.Series(raw, index=index).replace([np.inf, -np.inf], np.nan)
    # tanh keeps it smooth and bounded; fillna(0) = flat when undefined (warmup).
    return np.tanh(s).reindex(index).fillna(0.0).clip(-1.0, 1.0).astype(float)


# ─────────────────────────────────────────────────────────────────────────────
# Factor definitions. Each returns a RAW real-valued signal; _to_position wraps
# it. Comments cite the original formula being adapted.
# ─────────────────────────────────────────────────────────────────────────────

def _f_ts_reversal_1d(df: pd.DataFrame) -> pd.Series:
    # Alpha101 #1 family / short-horizon reversal: negative of recent return,
    # z-scored. Buy what fell, sell what rose, on the asset's own scale.
    r = df["Close"].pct_change()
    return _causal_z(-r)


def _f_reversal_5d(df: pd.DataFrame) -> pd.Series:
    # gtja191-style 5-day reversal: -(close_t / close_{t-5} - 1).
    mom5 = df["Close"] / df["Close"].shift(5) - 1.0
    return _causal_z(-mom5)


def _f_momentum_20d(df: pd.DataFrame) -> pd.Series:
    # Academic time-series momentum (Moskowitz-Ooi-Pedersen): +20d return.
    mom = df["Close"] / df["Close"].shift(20) - 1.0
    return _causal_z(mom)


def _f_momentum_60d(df: pd.DataFrame) -> pd.Series:
    # Slower TS-momentum leg; the managed-futures workhorse.
    mom = df["Close"] / df["Close"].shift(60) - 1.0
    return _causal_z(mom)


def _f_alpha101_101(df: pd.DataFrame) -> pd.Series:
    # Alpha101 #101 verbatim idea: (close - open) / (high - low + eps).
    # Intraday push: where did price close within the bar's range.
    rng = (df["High"] - df["Low"]).replace(0.0, np.nan)
    return _causal_z((df["Close"] - df["Open"]) / (rng + 1e-9))


def _f_alpha101_54(df: pd.DataFrame) -> pd.Series:
    # Alpha101 #54 idea: -((low - close)*open^5) / ((low - high)*close^5).
    # Reduces to a sign-stable measure of where close sits vs the range.
    low, high, close, open_ = df["Low"], df["High"], df["Close"], df["Open"]
    denom = ((low - high) * (close ** 5)).replace(0.0, np.nan)
    val = -((low - close) * (open_ ** 5)) / denom
    return _causal_z(val)


def _f_high_low_position(df: pd.DataFrame) -> pd.Series:
    # gtja191 #28-ish / Williams %R idea: position within trailing N-day range.
    win = 20
    hh = df["High"].rolling(win, min_periods=5).max()
    ll = df["Low"].rolling(win, min_periods=5).min()
    pos = (df["Close"] - ll) / (hh - ll).replace(0.0, np.nan)
    # Center at 0.5 → momentum sign; z-score for scale.
    return _causal_z(pos - 0.5)


def _f_volume_price_corr(df: pd.DataFrame) -> pd.Series:
    # Alpha101 #6 idea: -correlation(open, volume, 10). Causal rolling corr.
    win = 10
    c = df["Open"].rolling(win, min_periods=5).corr(df["Volume"])
    return _causal_z(-c)


def _f_volume_confirm_mom(df: pd.DataFrame) -> pd.Series:
    # gtja191 volume-confirmed momentum: sign(ret) weighted by volume z-score.
    r = df["Close"].pct_change()
    vz = _causal_z(df["Volume"])
    return _causal_z(np.sign(r) * vz.clip(-3, 3))


def _f_vol_scaled_reversal(df: pd.DataFrame) -> pd.Series:
    # Reversal scaled by realized vol (risk-aware): -ret / rolling_std(ret).
    r = df["Close"].pct_change()
    sd = r.rolling(20, min_periods=5).std(ddof=0).replace(0.0, np.nan)
    return _causal_z(-r / sd)


def _f_accel(df: pd.DataFrame) -> pd.Series:
    # Momentum acceleration: change in 10d momentum (2nd derivative of price).
    mom = df["Close"] / df["Close"].shift(10) - 1.0
    return _causal_z(mom.diff(5))


def _f_close_to_ma(df: pd.DataFrame) -> pd.Series:
    # Trend distance: close vs its own 50d MA, z-scored. Classic trend factor.
    ma = df["Close"].rolling(50, min_periods=10).mean()
    return _causal_z(df["Close"] / ma - 1.0)


@dataclass(frozen=True)
class AlphaFactor:
    name: str
    source: str  # "alpha101" | "gtja191" | "academic"
    desc: str
    fn: SignalFn

    def signal(self, df: pd.DataFrame) -> pd.Series:
        return _to_position(self.fn(df), df.index)


ZOO: list[AlphaFactor] = [
    AlphaFactor("ts_reversal_1d", "alpha101", "1-day reversal (z)", _f_ts_reversal_1d),
    AlphaFactor("reversal_5d", "gtja191", "5-day reversal (z)", _f_reversal_5d),
    AlphaFactor("momentum_20d", "academic", "20-day TS momentum", _f_momentum_20d),
    AlphaFactor("momentum_60d", "academic", "60-day TS momentum", _f_momentum_60d),
    AlphaFactor("alpha101_101", "alpha101", "(close-open)/range", _f_alpha101_101),
    AlphaFactor("alpha101_54", "alpha101", "range-position power form", _f_alpha101_54),
    AlphaFactor("hl_position_20d", "gtja191", "Williams %R style range pos", _f_high_low_position),
    AlphaFactor("vol_price_corr", "alpha101", "-corr(open,volume,10)", _f_volume_price_corr),
    AlphaFactor("vol_confirm_mom", "gtja191", "volume-confirmed momentum", _f_volume_confirm_mom),
    AlphaFactor("vol_scaled_reversal", "academic", "vol-scaled reversal", _f_vol_scaled_reversal),
    AlphaFactor("mom_accel", "academic", "momentum acceleration", _f_accel),
    AlphaFactor("close_to_ma50", "academic", "close vs 50d MA", _f_close_to_ma),
]


def bonferroni_alpha(alpha: float, n_tests: int) -> float:
    """Bonferroni-deflated significance bar for n simultaneous tests.

    The playbook lesson: brute-forcing many configs makes significance WORSE.
    If you test N factors, the bar to beat is alpha/N, not alpha.
    """
    return alpha / max(1, int(n_tests))


__all__ = ["ZOO", "AlphaFactor", "bonferroni_alpha", "SignalFn"]
