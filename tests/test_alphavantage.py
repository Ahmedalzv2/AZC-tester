"""Offline tests for the Alpha Vantage provider (no network/key needed)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from providers import PROVIDERS
from providers.base import DataSourceError, DatasetRequest


@pytest.fixture
def av():
    return PROVIDERS["alphavantage"]


def test_registered():
    assert "alphavantage" in PROVIDERS


def test_fx_intraday_url(av):
    url, _ = av._build_url("FX:GBPJPY", "5m", "USD", "K")
    assert "function=FX_INTRADAY" in url
    assert "from_symbol=GBP" in url and "to_symbol=JPY" in url
    assert "interval=5min" in url


def test_fx_daily_and_stock_and_crypto_urls(av):
    assert "function=FX_DAILY" in av._build_url("FX:EUR/USD", "1d", "USD", "K")[0]
    assert "function=TIME_SERIES_DAILY" in av._build_url("AAPL", "1d", "USD", "K")[0]
    assert "function=TIME_SERIES_INTRADAY" in av._build_url("STOCK:IBM", "15m", "USD", "K")[0]
    u = av._build_url("CRYPTO:BTC", "1d", "USD", "K")[0]
    assert "function=CRYPTO_DAILY" in u and "market=USD" in u


def test_parse_fx_daily(av):
    payload = {"Time Series FX (Daily)": {
        "2026-05-29": {"1. open": "190.1", "2. high": "191.2", "3. low": "189.5", "4. close": "190.8"},
        "2026-05-28": {"1. open": "189.0", "2. high": "190.5", "3. low": "188.7", "4. close": "190.1"},
    }}
    df = av._parse(payload)
    assert len(df) == 2
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert df.index.is_monotonic_increasing


def test_rate_limit_and_premium_surfaced(av):
    with pytest.raises(DataSourceError, match="rate limit"):
        av._parse({"Note": "call frequency is 25/day"})
    with pytest.raises(DataSourceError, match="premium"):
        av._parse({"Information": "premium endpoint"})


def test_no_key_gives_clear_error(av, monkeypatch):
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    monkeypatch.setattr("providers.alphavantage.KEY_FILE", Path("/nonexistent/key"))
    with pytest.raises(DataSourceError, match="API key"):
        av.fetch(DatasetRequest(provider="alphavantage", symbol="FX:GBPJPY", interval="1d"))
