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
    family = "generic"
    supports_files = False
    supports_remote = False
    supports_catalog = False
    requires_api_key = False
    supported_intervals: list[str] = []
    asset_classes: list[str] = []
    notes = ""

    def fetch(self, request: DatasetRequest) -> DatasetResponse:
        raise NotImplementedError

    def catalog(self) -> list[str]:
        return []

    def availability(self) -> dict[str, Any]:
        return {"available": True, "availability_reason": ""}

    def describe(self) -> dict[str, Any]:
        payload = {
            "label": self.label,
            "family": self.family,
            "supports_files": self.supports_files,
            "supports_remote": self.supports_remote,
            "supports_catalog": self.supports_catalog,
            "requires_api_key": self.requires_api_key,
            "supported_intervals": self.supported_intervals,
            "asset_classes": self.asset_classes,
            "notes": self.notes,
        }
        payload.update(self.availability())
        catalog = self.catalog()
        if catalog:
            payload["catalog"] = catalog
        return payload

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
        claimed: set[str] = set()
        # aliases is ordered so the real "close" is seen before "adj close";
        # whichever claims a canonical name first wins, so we never rename two
        # source columns to the same target (the duplicate-"Close" bug).
        for raw_name, canonical in aliases.items():
            original = column_map.get(raw_name)
            if original is not None and canonical not in claimed:
                rename_map[original] = canonical
                claimed.add(canonical)
        normalized = normalized.rename(columns=rename_map)
        # Belt-and-suspenders: drop any residual duplicate columns (e.g. an
        # upstream frame that already shipped two "Close"s), keeping the first.
        normalized = normalized.loc[:, ~normalized.columns.duplicated()]

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
