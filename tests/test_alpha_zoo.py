"""Tests for the Alpha Zoo: published quant factors ported as causal,
single-asset time-series signals.

The cardinal sin these tests guard against is lookahead. Alpha101/gtja191 are
largely *cross-sectional* factors; the honest single-asset port must be causal
— a signal at bar t may use only bars <= t. We borrow Vibe-Trading's idea of a
lookahead sentinel: mutating FUTURE bars must never change a PAST signal.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from alpha_zoo import ZOO, AlphaFactor, bonferroni_alpha


def _synthetic_ohlcv(n: int = 400, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0005, 0.02, n)
    close = 100 * np.exp(np.cumsum(rets))
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    high = close * (1 + np.abs(rng.normal(0, 0.01, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.01, n)))
    open_ = close * (1 + rng.normal(0, 0.005, n))
    vol = rng.integers(1_000, 10_000, n).astype(float)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol},
        index=idx,
    )


def test_zoo_is_nonempty_and_well_formed():
    assert len(ZOO) >= 8, "expected a meaningful set of ported factors"
    names = [f.name for f in ZOO]
    assert len(names) == len(set(names)), "factor names must be unique"
    for f in ZOO:
        assert isinstance(f, AlphaFactor)
        assert f.source in {"alpha101", "gtja191", "academic"}
        assert callable(f.fn)


@pytest.mark.parametrize("factor", ZOO, ids=lambda f: f.name)
def test_position_bounded_and_aligned(factor: AlphaFactor):
    df = _synthetic_ohlcv()
    pos = factor.signal(df)
    assert isinstance(pos, pd.Series)
    assert pos.index.equals(df.index)
    assert pos.notna().all(), f"{factor.name} produced NaNs"
    assert float(pos.abs().max()) <= 1.0 + 1e-9, f"{factor.name} exceeds [-1,1]"


@pytest.mark.parametrize("factor", ZOO, ids=lambda f: f.name)
def test_no_lookahead_sentinel(factor: AlphaFactor):
    """Mutating bars AFTER a cut point must not change signals BEFORE it.

    If a factor peeks into the future (e.g. a centered window, a full-sample
    normalization, or a .rank() over the whole series), this catches it.
    """
    df = _synthetic_ohlcv()
    cut = 300
    base = factor.signal(df).iloc[:cut].to_numpy()

    tampered = df.copy()
    rng = np.random.default_rng(123)
    # Violently perturb the future; the past signal must be byte-identical.
    fut = tampered.index[cut:]
    tampered.loc[fut, ["Open", "High", "Low", "Close"]] *= (
        1 + rng.normal(0, 0.5, (len(fut), 4))
    )
    tampered.loc[fut, "Volume"] *= 5
    after = factor.signal(tampered).iloc[:cut].to_numpy()

    np.testing.assert_allclose(
        base, after, rtol=0, atol=1e-9,
        err_msg=f"{factor.name} LOOKS AHEAD: future bars changed past signals",
    )


def test_bonferroni_alpha_scaling():
    # Cumulative Bonferroni: testing N hypotheses deflates the bar to alpha/N.
    assert bonferroni_alpha(0.05, 1) == pytest.approx(0.05)
    assert bonferroni_alpha(0.05, 10) == pytest.approx(0.005)
    assert bonferroni_alpha(0.05, 100) == pytest.approx(0.0005)
    # Never returns 0 or negative even for absurd N.
    assert bonferroni_alpha(0.05, 10_000) > 0
