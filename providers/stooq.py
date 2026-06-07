"""Stooq data provider — FREE long-history daily OHLCV (no key, no 25/day cap).

The whole point: Stooq serves DECADES of daily data as plain CSV, which is the
one thing yahoo (~2-5y) and Alpha Vantage free (25 req/day) can't. This is what
lets us test equity/FX/commodity trend over 20-30 years for free — the fair,
adequately-powered test the thin free sources couldn't support.

Symbols (Stooq convention, passed through as-is):
  US stocks/ETFs : spy.us, qqq.us, aapl.us
  Indices        : ^spx (S&P500, back to 1789), ^ndq (Nasdaq), ^dji
  FX             : eurusd, gbpjpy, usdjpy        (lowercase pair, no suffix)
  Commodities    : gc.f (gold), cl.f (WTI), si.f (silver)
Daily only here (i=d). Full history by default; cached to disk.
"""
from __future__ import annotations

import io
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import pandas as pd

from providers.base import CACHE_DIR, BaseDataProvider, DataSourceError, DatasetRequest, DatasetResponse

BASE = "https://stooq.com/q/d/l/"


class StooqProvider(BaseDataProvider):
    name = "stooq"
    label = "Stooq (free long-history daily)"
    family = "remote_api"
    supports_remote = True
    supports_catalog = False
    supported_intervals = ["1d"]
    asset_classes = ["equity", "index", "fx", "commodity"]
    notes = ("Decades of daily OHLCV, free, no key/limit. Symbols e.g. spy.us, ^spx, "
             "gbpjpy, gc.f. Best source for long-history daily trend tests.")

    def _cache_path(self, symbol: str) -> Path:
        return CACHE_DIR / f"{self.safe_file_name(symbol)}_1d_{self.name}.csv"

    def fetch(self, request: DatasetRequest) -> DatasetResponse:
        symbol = (request.symbol or "").strip().lower()
        if not symbol:
            raise DataSourceError("Stooq needs a symbol, e.g. spy.us, ^spx, gbpjpy, gc.f")
        cache = self._cache_path(symbol)
        from_cache = False

        if cache.exists() and not request.refresh:
            data = pd.read_csv(cache, index_col=0, parse_dates=True)
            from_cache = True
        else:
            url = f"{BASE}?s={urllib.parse.quote(symbol)}&i=d"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    text = resp.read().decode("utf-8", "replace")
            except Exception as exc:
                raise DataSourceError(f"Stooq fetch failed: {exc}") from exc
            head = text.strip()[:60].lower()
            if (not head.startswith("date")) or "no data" in head or "exceeded" in head:
                raise DataSourceError(f"Stooq returned no usable data for '{symbol}': {text.strip()[:80]}")
            raw = pd.read_csv(io.StringIO(text))
            if raw.empty or "Date" not in raw.columns or "Close" not in raw.columns:
                raise DataSourceError(f"Stooq response not OHLCV for '{symbol}'")
            raw.index = pd.to_datetime(raw.pop("Date"), utc=True)
            raw.index.name = "time"
            data = self.ensure_ohlcv(raw)
            data.to_csv(cache)

        if request.years > 0 and len(data) > 1:
            cutoff = data.index.max() - pd.Timedelta(days=int(request.years * 365))
            trimmed = data[data.index >= cutoff]
            if len(trimmed) > 50:
                data = trimmed.copy()

        source_info: dict[str, Any] = {
            "provider": self.name, "symbol": symbol, "interval": "1d",
            "requested_years": request.years, "from_cache": from_cache,
            "cache_file": str(cache),
            "source_note": "Stooq (cached)" if from_cache else "Stooq (fresh pull)",
        }
        dataset_info = {
            "rows": int(len(data)),
            "start": data.index[0].isoformat(), "end": data.index[-1].isoformat(),
        }
        return DatasetResponse(df=data, source_info=source_info, dataset_info=dataset_info)
