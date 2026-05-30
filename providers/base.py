from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd


class DataSourceError(RuntimeError):
    pass


@dataclass(slots=True)
class DatasetRequest:
    provider: str = "yahoo"
    symbol: str = "SPY"
    interval: str = "1d"
    years: int = 5
    refresh: bool = False
    file_path: str | None = None
    market: str | None = None
    timezone: str = "UTC"
    session: str | None = None


@dataclass(slots=True)
class DatasetResponse:
    df: pd.DataFrame
    source_info: dict[str, Any]
    dataset_info: dict[str, Any] = field(default_factory=dict)


class BaseDataProvider:
    name = "base"
    label = "Base provider"
    supports_files = False

    def fetch(self, request: DatasetRequest) -> DatasetResponse:
        raise NotImplementedError

    @staticmethod
    def ensure_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            raise DataSourceError("Upstream returned no rows")

        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = [col[0] for col in frame.columns]

        column_map = {str(col).strip().lower(): col for col in frame.columns}
        aliases = {
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "adj close": "Close",
            "volume": "Volume",
        }

        normalized = frame.copy()
        rename_map: dict[Any, str] = {}
        for raw_name, canonical in aliases.items():
            original = column_map.get(raw_name)
            if original is not None:
                rename_map[original] = canonical
        normalized = normalized.rename(columns=rename_map)

        if "Close" not in normalized.columns:
            raise DataSourceError("Dataset must include a close column")

        if not isinstance(normalized.index, pd.DatetimeIndex):
            if "Date" in normalized.columns:
                normalized.index = pd.to_datetime(normalized.pop("Date"), utc=True)
            elif "Datetime" in normalized.columns:
                normalized.index = pd.to_datetime(normalized.pop("Datetime"), utc=True)
            elif "timestamp" in column_map:
                raw = normalized.pop(column_map["timestamp"])
                normalized.index = pd.to_datetime(raw, utc=True)
            else:
                normalized.index = pd.to_datetime(normalized.index, utc=True)
        else:
            normalized.index = pd.to_datetime(normalized.index, utc=True)

        keep = [col for col in ["Open", "High", "Low", "Close", "Volume"] if col in normalized.columns]
        cleaned = normalized[keep].copy()

        for required in ["Open", "High", "Low"]:
            if required not in cleaned.columns:
                cleaned[required] = cleaned["Close"]
        if "Volume" not in cleaned.columns:
            cleaned["Volume"] = 0.0

        cleaned = cleaned[["Open", "High", "Low", "Close", "Volume"]]
        cleaned.index.name = "time"
        cleaned = cleaned[~cleaned.index.duplicated(keep="last")].sort_index()
        cleaned = cleaned.dropna(subset=["Close"])
        if cleaned.empty:
            raise DataSourceError("Dataset has no usable OHLCV rows after normalization")
        return cleaned.astype(float)

    @staticmethod
    def safe_file_name(value: str) -> str:
        return value.replace("/", "-").replace("=", "_").replace(":", "-")


CACHE_DIR = Path(__file__).resolve().parent.parent / "data_cache"
CACHE_DIR.mkdir(exist_ok=True)
