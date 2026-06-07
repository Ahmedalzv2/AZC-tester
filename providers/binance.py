from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from providers.base import CACHE_DIR, BaseDataProvider, DataSourceError, DatasetRequest, DatasetResponse

# Binance serves every interval the engine uses natively — no resampling needed.
# Values are ms-per-bar (used only as a sanity reference; pagination uses close_time).
BINANCE_INTERVALS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "1d": 86_400_000,
    "1wk": 604_800_000, "1mo": 2_592_000_000,  # parity aliases with yahoo naming
}
_INTERVAL_ALIAS = {"1wk": "1w", "1mo": "1M"}
_QUOTE_ASSETS = ("USDT", "USDC", "FDUSD", "BUSD", "TUSD", "BTC", "ETH", "BNB")
# Tried in order; .vision is the public market-data mirror (survives geo-blocks).
_BASE_HOSTS = (
    "https://api.binance.com/api/v3/klines",
    "https://data-api.binance.vision/api/v3/klines",
    "https://api1.binance.com/api/v3/klines",
)
_MAX_LIMIT = 1000


class BinanceProvider(BaseDataProvider):
    name = "binance"
    label = "Binance (spot klines)"
    family = "remote_api"
    supports_remote = True
    supported_intervals = list(BINANCE_INTERVALS.keys())
    asset_classes = ["crypto"]
    notes = "Deep native intraday history (years of 5m/15m). Symbols auto-mapped to USDT pairs (ETH -> ETHUSDT)."

    def _cache_path(self, symbol: str, interval: str) -> Path:
        return CACHE_DIR / f"{self.safe_file_name(symbol)}_{interval}_{self.name}.csv"

    @staticmethod
    def _stale(path: Path) -> bool:
        if not path.exists():
            return True
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        return datetime.now(tz=timezone.utc) - modified > timedelta(hours=12)

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        s = (symbol or "").strip().upper().replace("/", "").replace("-", "")
        if not s:
            raise DataSourceError("symbol is empty")
        for q in _QUOTE_ASSETS:
            if s.endswith(q) and len(s) > len(q):
                return s
        return s + "USDT"

    @staticmethod
    def _resolve_host(pair: str, api_interval: str) -> str:
        probe = {"symbol": pair, "interval": api_interval, "limit": 1}
        last_err = ""
        for host in _BASE_HOSTS:
            try:
                r = requests.get(host, params=probe, timeout=20)
            except requests.RequestException as exc:
                last_err = str(exc)
                continue
            if r.status_code == 200 and isinstance(r.json(), list):
                return host
            if r.status_code == 400:
                raise DataSourceError(f"Binance rejected {pair}/{api_interval}: {r.text[:200]}")
            last_err = f"HTTP {r.status_code} {r.text[:120]}"
        raise DataSourceError(f"No reachable Binance host (last: {last_err})")

    @staticmethod
    def _download(host: str, pair: str, api_interval: str, start_ms: int, end_ms: int) -> list:
        out: list = []
        cursor = start_ms
        guard = 0
        while cursor < end_ms and guard < 10_000:
            guard += 1
            params = {"symbol": pair, "interval": api_interval,
                      "startTime": cursor, "endTime": end_ms, "limit": _MAX_LIMIT}
            try:
                r = requests.get(host, params=params, timeout=30)
            except requests.RequestException as exc:
                raise DataSourceError(f"Binance request failed: {exc}") from exc
            if r.status_code in (429, 418):
                time.sleep(2.0)
                continue
            if r.status_code != 200:
                raise DataSourceError(f"Binance HTTP {r.status_code}: {r.text[:200]}")
            batch = r.json()
            if not batch:
                break
            out.extend(batch)
            nxt = int(batch[-1][6]) + 1   # last close_time + 1ms
            if nxt <= cursor:
                break
            cursor = nxt
            if len(batch) < _MAX_LIMIT:
                break
            time.sleep(0.05)
        return out

    def fetch(self, request: DatasetRequest) -> DatasetResponse:
        if request.interval not in BINANCE_INTERVALS:
            raise ValueError(f"Unsupported interval: {request.interval}")
        if request.years <= 0:
            raise ValueError("years must be positive")

        pair = self._normalize_symbol(request.symbol)
        cache_file = self._cache_path(pair, request.interval)
        source_info: dict[str, Any] = {
            "provider": self.name, "symbol": pair, "interval": request.interval,
            "requested_years": request.years, "cache_file": str(cache_file),
            "from_cache": False, "source_note": "",
        }

        if cache_file.exists() and not request.refresh and not self._stale(cache_file):
            cached = pd.read_csv(cache_file, index_col=0, parse_dates=True)
            cached.index = pd.to_datetime(cached.index, utc=True)
            source_info["from_cache"] = True
            source_info["source_note"] = "served from cache"
            clean = self.ensure_ohlcv(cached)
            return DatasetResponse(df=clean, source_info=source_info,
                                   dataset_info=self._dataset_info(clean, request))

        api_interval = _INTERVAL_ALIAS.get(request.interval, request.interval)
        now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        start_ms = now_ms - int(request.years * 365 * 86_400_000)
        host = self._resolve_host(pair, api_interval)
        rows = self._download(host, pair, api_interval, start_ms, now_ms)
        if not rows:
            raise DataSourceError("Upstream returned no rows")

        frame = pd.DataFrame(rows, columns=[
            "open_time", "Open", "High", "Low", "Close", "Volume",
            "close_time", "qav", "trades", "tbbav", "tbqav", "ignore"])
        frame.index = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
        frame = frame[["Open", "High", "Low", "Close", "Volume"]]
        data = self.ensure_ohlcv(frame)
        data.to_csv(cache_file)
        source_info["source_note"] = f"fresh upstream fetch ({len(data)} native {request.interval} bars via {host.split('/')[2]})"
        return DatasetResponse(df=data, source_info=source_info,
                               dataset_info=self._dataset_info(data, request))

    @staticmethod
    def _dataset_info(data: pd.DataFrame, request: DatasetRequest) -> dict[str, Any]:
        return {
            "market": request.market or "crypto",
            "timezone": request.timezone,
            "session": request.session or "24/7",
            "rows": int(len(data)),
            "start": data.index[0].isoformat(),
            "end": data.index[-1].isoformat(),
        }
