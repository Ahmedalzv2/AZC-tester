"""Alpha Vantage data provider — FX (incl. intraday), equities, crypto.

Why it matters for AZC: it unlocks the data we were missing. FX intraday
(GBPJPY at 1/5/15/60min) closes the "FX needs intraday data" open thread, and
20+ years of equities gives genuinely UNCORRELATED markets — the lever that
actually raises statistical power vs. piling on correlated alts.

Honest limits (free tier): 25 requests/day, and FX_INTRADAY / CRYPTO_INTRADAY /
full history are PREMIUM. So we cache aggressively (historical data is static)
and surface premium/rate-limit responses as clear errors instead of silent junk.

Symbol convention (so one provider covers three asset classes):
  FX:     "FX:GBPJPY"  or "FX:GBP/JPY"   -> FX_DAILY / FX_INTRADAY
  Stock:  "AAPL"        or "STOCK:AAPL"   -> TIME_SERIES_DAILY / _INTRADAY
  Crypto: "CRYPTO:BTC"  (market via request.market, default USD) -> CRYPTO_DAILY

Interval: "1d"/"daily" -> daily function; "1m/5m/15m/30m/1h" -> intraday.
API key: env ALPHAVANTAGE_API_KEY, else file /root/.alphavantage-key.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any

import pandas as pd

from providers.base import CACHE_DIR, BaseDataProvider, DataSourceError, DatasetRequest, DatasetResponse

BASE = "https://www.alphavantage.co/query"
KEY_FILE = Path("/root/.alphavantage-key")

# lab interval -> AV intraday interval
_INTRADAY = {"1m": "1min", "1min": "1min", "5m": "5min", "5min": "5min",
             "15m": "15min", "15min": "15min", "30m": "30min", "30min": "30min",
             "1h": "60min", "60m": "60min", "60min": "60min"}


def _api_key() -> str:
    key = os.environ.get("ALPHAVANTAGE_API_KEY", "").strip()
    if not key and KEY_FILE.exists():
        key = KEY_FILE.read_text().strip()
    if not key:
        raise DataSourceError(
            "No Alpha Vantage API key. Get a free one at "
            "https://www.alphavantage.co/support/#api-key then either set "
            "ALPHAVANTAGE_API_KEY or write it to /root/.alphavantage-key"
        )
    return key


class AlphaVantageProvider(BaseDataProvider):
    name = "alphavantage"
    label = "Alpha Vantage (FX / stocks / crypto)"
    family = "remote_api"
    supports_remote = True
    supports_catalog = False
    supported_intervals = ["1min", "5min", "15min", "30min", "60min", "1d"]
    asset_classes = ["fx", "equity", "crypto"]
    notes = ("FX intraday + 20y equities. Free tier = 25 req/day; intraday & full "
             "history are premium. Cached aggressively. Symbol e.g. FX:GBPJPY, AAPL, CRYPTO:BTC.")

    def _cache_path(self, symbol: str, interval: str) -> Path:
        return CACHE_DIR / f"{self.safe_file_name(symbol)}_{interval}_{self.name}.csv"

    def _build_url(self, symbol: str, interval: str, market: str, key: str) -> tuple[str, str]:
        """Returns (request_url, time_series_key_hint)."""
        intraday = interval.lower() not in ("1d", "1day", "daily", "")
        av_interval = _INTRADAY.get(interval.lower(), "60min") if intraday else None
        cls, _, sym = symbol.partition(":") if ":" in symbol else ("STOCK", "", symbol)
        cls = cls.upper()
        params = {"apikey": key, "datatype": "json", "outputsize": "full"}

        if cls == "FX":
            base = sym.replace("/", "")
            frm, to = base[:3], base[3:6]
            if intraday:
                params.update(function="FX_INTRADAY", from_symbol=frm, to_symbol=to, interval=av_interval)
            else:
                params.update(function="FX_DAILY", from_symbol=frm, to_symbol=to)
        elif cls == "CRYPTO":
            mkt = (market or "USD").upper()
            if intraday:
                params.update(function="CRYPTO_INTRADAY", symbol=sym, market=mkt, interval=av_interval)
            else:
                params.update(function="CRYPTO_DAILY", symbol=sym, market=mkt)
        else:  # equity
            if intraday:
                params.update(function="TIME_SERIES_INTRADAY", symbol=sym, interval=av_interval)
            else:
                params.update(function="TIME_SERIES_DAILY", symbol=sym)

        from urllib.parse import urlencode
        return f"{BASE}?{urlencode(params)}", "Time Series"

    def _parse(self, payload: dict[str, Any]) -> pd.DataFrame:
        # Surface AV's own status messages instead of returning empty junk.
        for flag, msg in (("Note", "rate limit (free tier = 25 req/day)"),
                          ("Information", "premium endpoint or invalid call"),
                          ("Error Message", "invalid symbol/parameters")):
            if flag in payload:
                raise DataSourceError(f"Alpha Vantage {msg}: {payload[flag]}")
        ts_key = next((k for k in payload if "Time Series" in k or "FX (Daily)" in k), None)
        if not ts_key:
            raise DataSourceError(f"Unexpected Alpha Vantage response: {list(payload)[:4]}")
        rows = []
        for ts, ohlc in payload[ts_key].items():
            rows.append((
                ts,
                float(ohlc.get("1. open", ohlc.get("1a. open (USD)", 0))),
                float(ohlc.get("2. high", ohlc.get("2a. high (USD)", 0))),
                float(ohlc.get("3. low", ohlc.get("3a. low (USD)", 0))),
                float(ohlc.get("4. close", ohlc.get("4a. close (USD)", 0))),
                float(ohlc.get("5. volume", ohlc.get("5. volume", 0)) or 0),
            ))
        frame = pd.DataFrame(rows, columns=["t", "Open", "High", "Low", "Close", "Volume"])
        frame.index = pd.to_datetime(frame.pop("t"), utc=True)
        frame.index.name = "time"
        return self.ensure_ohlcv(frame)

    def fetch(self, request: DatasetRequest) -> DatasetResponse:
        symbol = (request.symbol or "").strip()
        if not symbol:
            raise DataSourceError("Alpha Vantage needs a symbol, e.g. FX:GBPJPY, AAPL, CRYPTO:BTC")
        key = _api_key()
        cache = self._cache_path(symbol, request.interval)
        from_cache = False

        if cache.exists() and not request.refresh:
            data = pd.read_csv(cache, index_col=0, parse_dates=True)
            from_cache = True
        else:
            url, _ = self._build_url(symbol, request.interval, request.market or "USD", key)
            try:
                with urllib.request.urlopen(url, timeout=30) as resp:
                    payload = json.loads(resp.read().decode())
            except DataSourceError:
                raise
            except Exception as exc:  # network / decode
                raise DataSourceError(f"Alpha Vantage fetch failed: {exc}") from exc
            data = self._parse(payload)
            data.to_csv(cache)

        if request.years > 0 and len(data) > 1:
            cutoff = data.index.max() - pd.Timedelta(days=int(request.years * 365))
            trimmed = data[data.index >= cutoff]
            if len(trimmed) > 50:
                data = trimmed.copy()

        source_info: dict[str, Any] = {
            "provider": self.name, "symbol": symbol, "interval": request.interval,
            "requested_years": request.years, "from_cache": from_cache,
            "cache_file": str(cache),
            "source_note": "Alpha Vantage (cached)" if from_cache else "Alpha Vantage (fresh pull)",
        }
        dataset_info = {
            "rows": int(len(data)),
            "start": data.index[0].isoformat(), "end": data.index[-1].isoformat(),
        }
        return DatasetResponse(df=data, source_info=source_info, dataset_info=dataset_info)
