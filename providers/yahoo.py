from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

from providers.base import CACHE_DIR, BaseDataProvider, DatasetRequest, DatasetResponse

INTERVAL_LIMITS = {
    "1d": {"period": "max", "max_days": 365 * 100},
    "1wk": {"period": "max", "max_days": 365 * 100},
    "1mo": {"period": "max", "max_days": 365 * 100},
    "1h": {"period": "730d", "max_days": 730},
    "15m": {"period": "60d", "max_days": 60},
    "5m": {"period": "60d", "max_days": 60},
}


class YahooFinanceProvider(BaseDataProvider):
    name = "yahoo"
    label = "Yahoo Finance"
    family = "remote_api"
    supports_remote = True
    supported_intervals = list(INTERVAL_LIMITS.keys())
    asset_classes = ["stocks", "etf", "index", "fx", "crypto"]
    notes = "Daily bars are fine. Intraday depth is capped by Yahoo retention and trimmed honestly."

    def _cache_path(self, symbol: str, interval: str) -> Path:
        return CACHE_DIR / f"{self.safe_file_name(symbol)}_{interval}_{self.name}.csv"

    @staticmethod
    def _stale(path: Path) -> bool:
        if not path.exists():
            return True
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        return datetime.now(tz=timezone.utc) - modified > timedelta(hours=12)

    def fetch(self, request: DatasetRequest) -> DatasetResponse:
        if request.interval not in INTERVAL_LIMITS:
            raise ValueError(f"Unsupported interval: {request.interval}")
        if request.years <= 0:
            raise ValueError("years must be positive")

        cache_file = self._cache_path(request.symbol, request.interval)
        source_info: dict[str, Any] = {
            "provider": self.name,
            "symbol": request.symbol,
            "interval": request.interval,
            "requested_years": request.years,
            "cache_file": str(cache_file),
            "from_cache": False,
            "source_note": "",
        }

        if cache_file.exists() and not request.refresh and not self._stale(cache_file):
            cached = pd.read_csv(cache_file, index_col=0, parse_dates=True)
            cached.index = pd.to_datetime(cached.index, utc=True)
            source_info["from_cache"] = True
            source_info["source_note"] = "served from cache"
            clean = self.ensure_ohlcv(cached)
            return DatasetResponse(df=clean, source_info=source_info, dataset_info=self._dataset_info(clean, request))

        limits = INTERVAL_LIMITS[request.interval]
        requested_days = min(int(request.years * 365), limits["max_days"])
        if requested_days < int(request.years * 365):
            source_info["source_note"] = f"{request.interval} is limited by Yahoo history; trimmed to {requested_days} days"
        else:
            source_info["source_note"] = "fresh upstream fetch"

        ticker = yf.Ticker(request.symbol)
        frame = ticker.history(period=limits["period"], interval=request.interval, auto_adjust=False, actions=False)
        data = self.ensure_ohlcv(frame)
        cutoff = data.index.max() - pd.Timedelta(days=requested_days)
        data = data[data.index >= cutoff].copy()
        data.to_csv(cache_file)
        return DatasetResponse(df=data, source_info=source_info, dataset_info=self._dataset_info(data, request))

    @staticmethod
    def _dataset_info(data: pd.DataFrame, request: DatasetRequest) -> dict[str, Any]:
        return {
            "market": request.market or "unspecified",
            "timezone": request.timezone,
            "session": request.session or "default",
            "rows": int(len(data)),
            "start": data.index[0].isoformat(),
            "end": data.index[-1].isoformat(),
        }
