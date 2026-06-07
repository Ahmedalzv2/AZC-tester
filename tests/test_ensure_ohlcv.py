"""Regression tests for BaseDataProvider.ensure_ohlcv column normalization.

Why: yfinance returns both `Close` and `Adj Close`. The alias map sent both to
the canonical `Close`, producing two `Close` columns; downstream `df["Close"]`
then returned a 2-D frame and the engine raised
"Data must be 1-dimensional, got ndarray of shape (N, 2)".
"""

import numpy as np
import pandas as pd

from providers.base import BaseDataProvider


def _yahoo_like_frame(rows: int = 5) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=rows, freq="D", tz="UTC")
    base = np.arange(rows, dtype=float) + 100.0
    return pd.DataFrame(
        {
            "Open": base,
            "High": base + 1,
            "Low": base - 1,
            "Close": base + 0.5,
            "Adj Close": base + 0.4,  # the troublemaker
            "Volume": np.full(rows, 1000.0),
        },
        index=idx,
    )


def test_adj_close_does_not_duplicate_close():
    cleaned = BaseDataProvider.ensure_ohlcv(_yahoo_like_frame())
    assert list(cleaned.columns) == ["Open", "High", "Low", "Close", "Volume"]
    # The real Close must win, not Adj Close.
    assert cleaned["Close"].iloc[0] == 100.5


def test_close_is_one_dimensional():
    cleaned = BaseDataProvider.ensure_ohlcv(_yahoo_like_frame())
    close = cleaned["Close"]
    assert isinstance(close, pd.Series)
    assert close.values.ndim == 1


def test_adj_close_only_falls_back_to_close():
    frame = _yahoo_like_frame().drop(columns=["Close"])
    cleaned = BaseDataProvider.ensure_ohlcv(frame)
    assert "Close" in cleaned.columns
    assert cleaned["Close"].iloc[0] == 100.4
