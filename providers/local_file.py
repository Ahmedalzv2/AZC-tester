from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from providers.base import BaseDataProvider, DataSourceError, DatasetRequest, DatasetResponse


class LocalFileProvider(BaseDataProvider):
    name = "local_file"
    label = "Local CSV / Parquet"
    family = "file_import"
    supports_files = True
    supported_intervals = ["any"]
    asset_classes = ["stocks", "crypto", "forex", "futures", "options", "custom"]
    notes = "Best generic path for long research histories. Reads VPS-local CSV/Parquet directly."

    def fetch(self, request: DatasetRequest) -> DatasetResponse:
        if not request.file_path:
            raise DataSourceError("file_path is required for local_file provider")

        path = Path(request.file_path).expanduser()
        if not path.exists():
            raise DataSourceError(f"File not found: {path}")
        if path.is_dir():
            raise DataSourceError(f"Expected a file, got directory: {path}")

        suffix = path.suffix.lower()
        if suffix == ".csv":
            raw = pd.read_csv(path)
        elif suffix in {".parquet", ".pq"}:
            raw = pd.read_parquet(path)
        else:
            raise DataSourceError("Unsupported local file type. Use .csv or .parquet")

        data = self.ensure_ohlcv(raw)
        if request.years > 0 and len(data) > 1:
            cutoff = data.index.max() - pd.Timedelta(days=int(request.years * 365))
            data = data[data.index >= cutoff].copy()

        source_info: dict[str, Any] = {
            "provider": self.name,
            "symbol": request.symbol or path.stem,
            "interval": request.interval,
            "requested_years": request.years,
            "cache_file": "",
            "from_cache": False,
            "source_note": f"loaded directly from {path}",
            "file_path": str(path),
            "file_type": suffix,
        }
        dataset_info = {
            "market": request.market or "unspecified",
            "timezone": request.timezone,
            "session": request.session or "default",
            "rows": int(len(data)),
            "start": data.index[0].isoformat(),
            "end": data.index[-1].isoformat(),
        }
        return DatasetResponse(df=data, source_info=source_info, dataset_info=dataset_info)
