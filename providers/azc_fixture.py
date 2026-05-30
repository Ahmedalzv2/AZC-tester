"""AZC crypto fixtures provider.

Serves the OHLCV fixtures bundled with the AZC repo (DOGE/SOL/XRP at 5m/15m/1h)
so the dashboard can reproduce the live crypto research against the exact same
tape the AZC backtester uses. The container mounts /root:/root, so these are
read in place — no copying.

`symbol` is the fixture stem, e.g. "SOL-365d-Min15". GET /api/providers exposes
the catalogue. Bars are returned at their native interval; the AZC bracket
strategies aggregate to 4h themselves.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from providers.base import BaseDataProvider, DataSourceError, DatasetRequest, DatasetResponse

FIXTURE_DIR = Path("/root/apps/ict-autopilot/tests/fixtures")


def available_fixtures() -> list[str]:
    if not FIXTURE_DIR.exists():
        return []
    out = []
    for f in sorted(FIXTURE_DIR.glob("*-Min*.json")):
        # OHLCV klines only — skip funding/news/topic side files.
        if any(tag in f.stem for tag in ("funding", "news", "topic", "lc-")):
            continue
        out.append(f.stem)
    return out


class AzcFixtureProvider(BaseDataProvider):
    name = "azc_fixture"
    label = "AZC Crypto Fixtures (DOGE/SOL/XRP)"
    supports_files = False

    def fetch(self, request: DatasetRequest) -> DatasetResponse:
        symbol = (request.symbol or "").strip()
        if not symbol:
            raise DataSourceError(
                f"Pick a fixture symbol. Available: {', '.join(available_fixtures()) or '(none mounted)'}"
            )
        path = FIXTURE_DIR / f"{symbol}.json"
        if not path.exists():
            raise DataSourceError(
                f"Unknown fixture '{symbol}'. Available: {', '.join(available_fixtures()) or '(none mounted)'}"
            )

        raw = json.loads(path.read_text())
        rows = []
        for r in raw:
            if isinstance(r, dict):
                rows.append((r["t"], r.get("o"), r.get("h"), r.get("l"), r.get("c"), r.get("v", 0.0)))
            else:  # positional [t,o,h,l,c,(v)]
                rows.append((r[0], r[1], r[2], r[3], r[4], r[5] if len(r) > 5 else 0.0))
        frame = pd.DataFrame(rows, columns=["t", "Open", "High", "Low", "Close", "Volume"])
        frame.index = pd.to_datetime(frame.pop("t"), unit="ms", utc=True)
        frame.index.name = "time"
        data = self.ensure_ohlcv(frame)

        if request.years > 0 and len(data) > 1:
            cutoff = data.index.max() - pd.Timedelta(days=int(request.years * 365))
            trimmed = data[data.index >= cutoff]
            if len(trimmed) > 50:  # don't trim a short fixture into uselessness
                data = trimmed.copy()

        source_info: dict[str, Any] = {
            "provider": self.name,
            "symbol": symbol,
            "interval": request.interval,
            "requested_years": request.years,
            "from_cache": True,
            "source_note": f"AZC fixture {path.name}",
            "available": available_fixtures(),
        }
        dataset_info = {
            "market": "crypto-perp (MEXC)",
            "timezone": "UTC",
            "rows": int(len(data)),
            "start": data.index[0].isoformat(),
            "end": data.index[-1].isoformat(),
        }
        return DatasetResponse(df=data, source_info=source_info, dataset_info=dataset_info)
