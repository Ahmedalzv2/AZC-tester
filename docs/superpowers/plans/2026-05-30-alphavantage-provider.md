# AlphaVantage Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an AlphaVantage daily data provider to backtest-lab plus a cross-check utility that diffs the same symbol across providers.

**Architecture:** A new `AlphaVantageProvider(BaseDataProvider)` mirrors the existing `yahoo.py` (remote fetch + 12h CSV cache + `ensure_ohlcv` normalization). One symbol resolver maps Yahoo-style tickers to AlphaVantage's per-asset-class argument shapes; one series parser handles FX/crypto/equity JSON; quota/error responses (returned as HTTP 200) are detected and raised as `DataSourceError`. A standalone `data_check.py` fetches a symbol from two providers and reports close-price divergence.

**Tech Stack:** Python, pandas, requests, FastAPI app, pytest.

**Constraints:** Free API key (25 req/day, 5/min) — daily only; intraday is guarded behind `ALPHAVANTAGE_PREMIUM`. Shared working tree with Hermes — commits are path-scoped to only the files each task touches; never `git add -A`.

---

## File Structure

- **Create** `providers/alphavantage.py` — the provider class + helpers (`_resolve_symbol`, `_extract_series`, `_series_to_frame`, `_cache_path`, `_stale`, `fetch`).
- **Modify** `providers/__init__.py` — register the provider.
- **Create** `data_check.py` — `cross_check_history()` divergence utility.
- **Create** `tests/fixtures/alphavantage/*.json` — recorded sample responses.
- **Create** `tests/test_alphavantage_provider.py` — provider unit tests.
- **Create** `tests/test_data_check.py` — cross-check unit tests.
- **Modify** `tests/test_providers_metadata.py` — assert new provider metadata.
- **Modify** `requirements.txt` — add `requests`.
- **Modify** `docker-compose.yml` + `.gitignore` — wire `ALPHAVANTAGE_API_KEY` via uncommitted `.env`.

---

### Task 1: Add dependency and register an empty provider skeleton

**Files:**
- Modify: `requirements.txt`
- Create: `providers/alphavantage.py`
- Modify: `providers/__init__.py`
- Modify: `tests/test_providers_metadata.py`

- [ ] **Step 1: Add the failing metadata assertion**

In `tests/test_providers_metadata.py`, add to `test_provider_registry_exposes_metadata`:

```python
    assert providers["alphavantage"]["supports_remote"] is True
    assert "fx" in providers["alphavantage"]["asset_classes"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_providers_metadata.py -v`
Expected: FAIL with `KeyError: 'alphavantage'`.

- [ ] **Step 3: Add `requests` to requirements**

Append to `requirements.txt`:

```
requests
```

- [ ] **Step 4: Create the provider skeleton**

Create `providers/alphavantage.py`:

```python
"""AlphaVantage data provider (daily-first).

Free tier is 25 requests/day, 5/min, so this serves daily FX / crypto / equity
history (cached 12h, one request per symbol) and treats intraday as
premium-only. Intervals map to AlphaVantage's per-asset-class argument shapes;
quota and error responses come back as HTTP 200 JSON and are surfaced as
DataSourceError instead of being fed downstream.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from providers.base import CACHE_DIR, BaseDataProvider, DataSourceError, DatasetRequest, DatasetResponse

BASE_URL = "https://www.alphavantage.co/query"

# Daily intervals AlphaVantage serves for free; intraday is premium-gated below.
DAILY_INTERVALS = {"1d", "1wk", "1mo"}
INTRADAY_INTERVALS = {"5m", "15m", "30m", "60m"}

# Three-letter fiat codes used to disambiguate slash-form pairs (GBP/JPY = FX,
# BTC/USD = crypto). Yahoo-style suffixes (=X, -USD) are the primary signal.
FIAT = {"USD", "EUR", "JPY", "GBP", "CHF", "AUD", "CAD", "NZD", "CNH", "CNY", "HKD", "SGD"}


class AlphaVantageProvider(BaseDataProvider):
    name = "alphavantage"
    label = "AlphaVantage (daily)"
    family = "remote_api"
    supports_remote = True
    supported_intervals = sorted(DAILY_INTERVALS | INTRADAY_INTERVALS)
    asset_classes = ["fx", "crypto", "stocks", "etf"]
    notes = "Free tier = 25 req/day. Daily FX/crypto/equity only; intraday needs ALPHAVANTAGE_PREMIUM."

    def fetch(self, request: DatasetRequest) -> DatasetResponse:
        raise NotImplementedError  # filled in by later tasks
```

- [ ] **Step 5: Register the provider**

In `providers/__init__.py`, add the import beside the others:

```python
from providers.alphavantage import AlphaVantageProvider
```

and add to the `PROVIDERS` dict:

```python
    AlphaVantageProvider.name: AlphaVantageProvider(),
```

- [ ] **Step 6: Run the metadata test to verify it passes**

Run: `python -m pytest tests/test_providers_metadata.py -v`
Expected: PASS.

- [ ] **Step 7: Commit (path-scoped)**

```bash
git add requirements.txt providers/alphavantage.py providers/__init__.py tests/test_providers_metadata.py
git commit -m "feat(alphavantage): register provider skeleton + requests dep"
```

---

### Task 2: Symbol resolver

**Files:**
- Modify: `providers/alphavantage.py`
- Create: `tests/test_alphavantage_provider.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_alphavantage_provider.py`:

```python
from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from providers.alphavantage import AlphaVantageProvider
from providers.base import DataSourceError


def test_resolve_fx_yahoo_suffix():
    func, params, asset = AlphaVantageProvider()._resolve_symbol("GBPJPY=X")
    assert func == "FX_DAILY"
    assert params == {"from_symbol": "GBP", "to_symbol": "JPY"}
    assert asset == "fx"


def test_resolve_crypto_dash():
    func, params, asset = AlphaVantageProvider()._resolve_symbol("BTC-USD")
    assert func == "DIGITAL_CURRENCY_DAILY"
    assert params == {"symbol": "BTC", "market": "USD"}
    assert asset == "crypto"


def test_resolve_slash_fx_vs_crypto():
    av = AlphaVantageProvider()
    assert av._resolve_symbol("GBP/JPY")[0] == "FX_DAILY"
    assert av._resolve_symbol("BTC/USD")[0] == "DIGITAL_CURRENCY_DAILY"


def test_resolve_equity():
    func, params, asset = AlphaVantageProvider()._resolve_symbol("SPY")
    assert func == "TIME_SERIES_DAILY"
    assert params == {"symbol": "SPY"}
    assert asset == "stocks"


def test_resolve_unmappable_raises():
    with pytest.raises(DataSourceError):
        AlphaVantageProvider()._resolve_symbol("")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_alphavantage_provider.py -v`
Expected: FAIL with `AttributeError: ... has no attribute '_resolve_symbol'`.

- [ ] **Step 3: Implement `_resolve_symbol`**

Add to the `AlphaVantageProvider` class in `providers/alphavantage.py`:

```python
    def _resolve_symbol(self, symbol: str) -> tuple[str, dict[str, str], str]:
        raw = (symbol or "").strip().upper()
        if not raw:
            raise DataSourceError("AlphaVantage: empty symbol")

        # Yahoo FX suffix: GBPJPY=X -> GBP/JPY
        if raw.endswith("=X"):
            core = raw[:-2]
            if len(core) == 6:
                return "FX_DAILY", {"from_symbol": core[:3], "to_symbol": core[3:]}, "fx"
            raise DataSourceError(f"AlphaVantage: cannot parse FX symbol '{symbol}'")

        # Separator forms: BTC-USD (crypto) or GBP/JPY (fx) or BTC/USD (crypto).
        for sep in ("-", "/"):
            if sep in raw:
                base, _, quote = raw.partition(sep)
                if not base or not quote:
                    raise DataSourceError(f"AlphaVantage: cannot parse pair '{symbol}'")
                # Both legs fiat => FX; otherwise treat the base as a crypto asset.
                if base in FIAT and quote in FIAT:
                    return "FX_DAILY", {"from_symbol": base, "to_symbol": quote}, "fx"
                return "DIGITAL_CURRENCY_DAILY", {"symbol": base, "market": quote}, "crypto"

        # No separator: plain equity/ETF ticker.
        return "TIME_SERIES_DAILY", {"symbol": raw}, "stocks"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_alphavantage_provider.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add providers/alphavantage.py tests/test_alphavantage_provider.py
git commit -m "feat(alphavantage): symbol resolver for fx/crypto/equity"
```

---

### Task 3: Error-as-HTTP-200 detection + series extraction

**Files:**
- Modify: `providers/alphavantage.py`
- Modify: `tests/test_alphavantage_provider.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_alphavantage_provider.py`:

```python
def test_extract_series_raises_on_note():
    with pytest.raises(DataSourceError) as exc:
        AlphaVantageProvider()._extract_series({"Note": "rate limit reached"})
    assert "rate limit" in str(exc.value).lower()


def test_extract_series_raises_on_information():
    with pytest.raises(DataSourceError):
        AlphaVantageProvider()._extract_series({"Information": "premium endpoint"})


def test_extract_series_raises_on_error_message():
    with pytest.raises(DataSourceError):
        AlphaVantageProvider()._extract_series({"Error Message": "invalid symbol"})


def test_extract_series_returns_time_series_block():
    payload = {"Meta Data": {}, "Time Series FX (Daily)": {"2024-01-02": {"1. open": "1.0"}}}
    series = AlphaVantageProvider()._extract_series(payload)
    assert series == {"2024-01-02": {"1. open": "1.0"}}


def test_extract_series_raises_when_no_series():
    with pytest.raises(DataSourceError):
        AlphaVantageProvider()._extract_series({"Meta Data": {}})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_alphavantage_provider.py -k extract_series -v`
Expected: FAIL with `AttributeError: ... '_extract_series'`.

- [ ] **Step 3: Implement `_extract_series`**

Add to the class:

```python
    @staticmethod
    def _extract_series(payload: dict[str, Any]) -> dict[str, Any]:
        # AlphaVantage signals quota/errors with HTTP 200 + these keys.
        for key in ("Error Message", "Note", "Information"):
            if key in payload:
                raise DataSourceError(f"AlphaVantage: {payload[key]}")
        for key, value in payload.items():
            if key.startswith("Time Series") and isinstance(value, dict):
                return value
        raise DataSourceError("AlphaVantage: response contained no time series")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_alphavantage_provider.py -k extract_series -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add providers/alphavantage.py tests/test_alphavantage_provider.py
git commit -m "feat(alphavantage): detect quota/error-as-200 responses"
```

---

### Task 4: Series-to-OHLCV parser (FX + crypto + equity, incl. legacy crypto)

**Files:**
- Modify: `providers/alphavantage.py`
- Modify: `tests/test_alphavantage_provider.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_alphavantage_provider.py`:

```python
def test_parse_fx_series_no_volume_filled_zero():
    series = {
        "2024-01-03": {"1. open": "1.10", "2. high": "1.20", "3. low": "1.05", "4. close": "1.15"},
        "2024-01-02": {"1. open": "1.00", "2. high": "1.12", "3. low": "0.99", "4. close": "1.10"},
    }
    df = AlphaVantageProvider()._series_to_frame(series)
    df = AlphaVantageProvider.ensure_ohlcv(df)
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert df.iloc[0]["Volume"] == 0.0
    assert df.index.is_monotonic_increasing
    assert df.iloc[-1]["Close"] == 1.15


def test_parse_crypto_current_schema():
    series = {
        "2024-01-02": {
            "1. open": "42000.0", "2. high": "43000.0",
            "3. low": "41000.0", "4. close": "42500.0", "5. volume": "1234.5",
        }
    }
    df = AlphaVantageProvider.ensure_ohlcv(AlphaVantageProvider()._series_to_frame(series))
    assert df.iloc[0]["Close"] == 42500.0
    assert df.iloc[0]["Volume"] == 1234.5


def test_parse_crypto_legacy_prefers_usd_columns():
    series = {
        "2024-01-02": {
            "1a. open (USD)": "42000.0", "1b. open (USD)": "42000.0",
            "2a. high (USD)": "43000.0", "3a. low (USD)": "41000.0",
            "4a. close (USD)": "42500.0", "4b. close (USD)": "42500.0",
            "5. volume": "10.0", "6. market cap (USD)": "999999.0",
        }
    }
    df = AlphaVantageProvider.ensure_ohlcv(AlphaVantageProvider()._series_to_frame(series))
    assert df.iloc[0]["Close"] == 42500.0
    assert df.iloc[0]["High"] == 43000.0
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_alphavantage_provider.py -k parse -v`
Expected: FAIL with `AttributeError: ... '_series_to_frame'`.

- [ ] **Step 3: Implement `_series_to_frame`**

Add to the class:

```python
    @staticmethod
    def _series_to_frame(series: dict[str, Any]) -> pd.DataFrame:
        rows: dict[str, dict[str, float]] = {}
        for date, fields in series.items():
            bar: dict[str, float] = {}
            for raw_name, raw_value in fields.items():
                # Strip the "N. " / "Na. " prefix -> "open (usd)", "close", "volume".
                name = raw_name.split(". ", 1)[-1].lower()
                prefer_usd = "usd" in name
                matched = False
                for col, token in (("Open", "open"), ("High", "high"),
                                   ("Low", "low"), ("Close", "close")):
                    if token in name and "market cap" not in name:
                        if col not in bar or prefer_usd:
                            bar[col] = float(raw_value)
                        matched = True
                        break
                if not matched and "volume" in name:
                    bar["Volume"] = float(raw_value)
            rows[date] = bar
        frame = pd.DataFrame.from_dict(rows, orient="index")
        frame.index = pd.to_datetime(frame.index, utc=True)
        return frame
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_alphavantage_provider.py -k parse -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add providers/alphavantage.py tests/test_alphavantage_provider.py
git commit -m "feat(alphavantage): parse fx/crypto/equity series into OHLCV"
```

---

### Task 5: `fetch()` with guards, caching, and recorded-fixture network test

**Files:**
- Modify: `providers/alphavantage.py`
- Create: `tests/fixtures/alphavantage/fx_daily_gbpjpy.json`
- Modify: `tests/test_alphavantage_provider.py`

- [ ] **Step 1: Create a recorded fixture**

Create `tests/fixtures/alphavantage/fx_daily_gbpjpy.json`:

```json
{
  "Meta Data": {"1. Information": "Forex Daily Prices", "2. From Symbol": "GBP", "3. To Symbol": "JPY"},
  "Time Series FX (Daily)": {
    "2024-01-04": {"1. open": "185.00", "2. high": "186.50", "3. low": "184.80", "4. close": "186.20"},
    "2024-01-03": {"1. open": "184.20", "2. high": "185.40", "3. low": "183.90", "4. close": "185.00"},
    "2024-01-02": {"1. open": "183.00", "2. high": "184.50", "3. low": "182.70", "4. close": "184.20"}
  }
}
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_alphavantage_provider.py`:

```python
import json

from providers.base import DatasetRequest

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "alphavantage"


def test_fetch_missing_key_raises(monkeypatch):
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    with pytest.raises(DataSourceError) as exc:
        AlphaVantageProvider().fetch(DatasetRequest(provider="alphavantage", symbol="GBPJPY=X", interval="1d"))
    assert "ALPHAVANTAGE_API_KEY" in str(exc.value)


def test_fetch_intraday_on_free_raises(monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "demo")
    monkeypatch.delenv("ALPHAVANTAGE_PREMIUM", raising=False)
    with pytest.raises(DataSourceError) as exc:
        AlphaVantageProvider().fetch(DatasetRequest(provider="alphavantage", symbol="GBPJPY=X", interval="5m"))
    assert "premium" in str(exc.value).lower()


def test_fetch_fx_daily_from_fixture(monkeypatch, tmp_path):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "demo")
    payload = json.loads((FIXTURES / "fx_daily_gbpjpy.json").read_text())

    class FakeResp:
        def json(self_inner):
            return payload
        def raise_for_status(self_inner):
            return None

    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["params"] = params
        return FakeResp()

    monkeypatch.setattr("providers.alphavantage.requests.get", fake_get)
    # Redirect cache so the test never touches the real data_cache.
    monkeypatch.setattr("providers.alphavantage.CACHE_DIR", tmp_path)

    resp = AlphaVantageProvider().fetch(
        DatasetRequest(provider="alphavantage", symbol="GBPJPY=X", interval="1d", years=5)
    )
    assert captured["params"]["function"] == "FX_DAILY"
    assert captured["params"]["from_symbol"] == "GBP"
    assert captured["params"]["outputsize"] == "full"
    assert len(resp.df) == 3
    assert resp.df.iloc[-1]["Close"] == 186.20
    assert resp.df["Volume"].sum() == 0.0
    # Second call with a warm cache must not hit the network.
    monkeypatch.setattr("providers.alphavantage.requests.get",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("network hit")))
    cached = AlphaVantageProvider().fetch(
        DatasetRequest(provider="alphavantage", symbol="GBPJPY=X", interval="1d", years=5)
    )
    assert cached.source_info["from_cache"] is True
```

- [ ] **Step 3: Run them to verify they fail**

Run: `python -m pytest tests/test_alphavantage_provider.py -k fetch -v`
Expected: FAIL — `fetch` currently raises `NotImplementedError`.

- [ ] **Step 4: Implement `fetch`, `_cache_path`, `_stale`**

Replace the placeholder `fetch` in `providers/alphavantage.py` and add the cache helpers:

```python
    def _cache_path(self, symbol: str, interval: str) -> Path:
        return CACHE_DIR / f"{self.safe_file_name(symbol)}_{interval}_{self.name}.csv"

    @staticmethod
    def _stale(path: Path) -> bool:
        if not path.exists():
            return True
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        return datetime.now(tz=timezone.utc) - modified > timedelta(hours=12)

    def fetch(self, request: DatasetRequest) -> DatasetResponse:
        if request.interval in INTRADAY_INTERVALS and not os.environ.get("ALPHAVANTAGE_PREMIUM"):
            raise DataSourceError(
                "AlphaVantage intraday needs a premium key — set ALPHAVANTAGE_PREMIUM=1 once you have one"
            )
        if request.interval not in DAILY_INTERVALS:
            raise DataSourceError(f"AlphaVantage: unsupported interval '{request.interval}'")
        if request.years <= 0:
            raise ValueError("years must be positive")

        api_key = os.environ.get("ALPHAVANTAGE_API_KEY")
        if not api_key:
            raise DataSourceError("Set ALPHAVANTAGE_API_KEY to use the AlphaVantage provider")

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
            return DatasetResponse(df=clean, source_info=source_info,
                                   dataset_info=self._dataset_info(clean, request))

        function, params, asset_class = self._resolve_symbol(request.symbol)
        query = {"function": function, "apikey": api_key, "outputsize": "full", **params}
        try:
            response = requests.get(BASE_URL, params=query, timeout=30)
            response.raise_for_status()
            payload = response.json()
        except DataSourceError:
            raise
        except Exception as err:  # network / decode
            raise DataSourceError(f"AlphaVantage request failed: {err}") from err

        series = self._extract_series(payload)
        frame = self._series_to_frame(series)
        data = self.ensure_ohlcv(frame)

        cutoff = data.index.max() - pd.Timedelta(days=int(request.years * 365))
        data = data[data.index >= cutoff].copy()
        data.to_csv(cache_file)
        source_info["source_note"] = f"fresh fetch ({asset_class}, {function})"
        return DatasetResponse(df=data, source_info=source_info,
                               dataset_info=self._dataset_info(data, request))

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
```

> Note: the test patches `providers.alphavantage.CACHE_DIR`. Because `fetch` and `_cache_path` reference the module-level `CACHE_DIR`, the monkeypatch takes effect — do not import `CACHE_DIR` into a local variable at call time.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_alphavantage_provider.py -v`
Expected: PASS (all provider tests, including cache reuse).

- [ ] **Step 6: Commit**

```bash
git add providers/alphavantage.py tests/test_alphavantage_provider.py tests/fixtures/alphavantage/fx_daily_gbpjpy.json
git commit -m "feat(alphavantage): fetch with key/intraday guards + 12h cache"
```

---

### Task 6: Cross-check utility

**Files:**
- Create: `data_check.py`
- Create: `tests/test_data_check.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_data_check.py`:

```python
from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))

import data_check


def _frame(closes, start="2024-01-01"):
    idx = pd.date_range(start, periods=len(closes), freq="D", tz="UTC")
    return pd.DataFrame(
        {"Open": closes, "High": closes, "Low": closes, "Close": closes, "Volume": 0.0},
        index=idx,
    )


def test_cross_check_reports_divergence(monkeypatch):
    a = _frame([100.0, 101.0, 102.0])
    b = _frame([100.0, 101.0, 110.0])  # last bar diverges ~7.8%

    def fake_fetch(symbol, interval="1d", provider="yahoo", **kwargs):
        return (a if provider == "yahoo" else b), {"provider": provider}

    monkeypatch.setattr(data_check, "fetch_history", fake_fetch)

    out = data_check.cross_check_history("BTC-USD", providers=("yahoo", "alphavantage"))
    assert out["overlap_rows"] == 3
    assert out["max_abs_close_pct"] > 7.0
    assert out["bars_over_threshold"] == 1
    assert out["worst"][0]["pct"] > 7.0


def test_cross_check_handles_no_overlap(monkeypatch):
    a = _frame([100.0, 101.0], start="2024-01-01")
    b = _frame([100.0, 101.0], start="2025-01-01")

    def fake_fetch(symbol, interval="1d", provider="yahoo", **kwargs):
        return (a if provider == "yahoo" else b), {"provider": provider}

    monkeypatch.setattr(data_check, "fetch_history", fake_fetch)
    out = data_check.cross_check_history("BTC-USD", providers=("yahoo", "alphavantage"))
    assert out["overlap_rows"] == 0
    assert out["max_abs_close_pct"] is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_data_check.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'data_check'`.

- [ ] **Step 3: Implement `data_check.py`**

Create `data_check.py`:

```python
"""Cross-check the same symbol across two providers.

Truth-layer helper: pull a symbol's daily bars from two sources, align on the
shared date index, and report where the closes disagree. Catches silent Yahoo
data errors against AlphaVantage (and vice versa).
"""
from __future__ import annotations

from typing import Any

from data_source import fetch_history


def cross_check_history(
    symbol: str,
    interval: str = "1d",
    years: int = 5,
    providers: tuple[str, str] = ("yahoo", "alphavantage"),
    threshold_pct: float = 0.5,
    worst_n: int = 10,
) -> dict[str, Any]:
    left_name, right_name = providers
    left, _ = fetch_history(symbol, interval=interval, years=years, provider=left_name)
    right, _ = fetch_history(symbol, interval=interval, years=years, provider=right_name)

    joined = left[["Close"]].join(
        right[["Close"]], how="inner", lsuffix="_l", rsuffix="_r"
    )
    result: dict[str, Any] = {
        "symbol": symbol,
        "interval": interval,
        "providers": list(providers),
        "rows_left": int(len(left)),
        "rows_right": int(len(right)),
        "overlap_rows": int(len(joined)),
        "threshold_pct": threshold_pct,
        "max_abs_close_pct": None,
        "mean_abs_close_pct": None,
        "bars_over_threshold": 0,
        "worst": [],
    }
    if joined.empty:
        return result

    pct = ((joined["Close_l"] - joined["Close_r"]).abs() / joined["Close_r"].abs()) * 100.0
    result["max_abs_close_pct"] = float(pct.max())
    result["mean_abs_close_pct"] = float(pct.mean())
    result["bars_over_threshold"] = int((pct > threshold_pct).sum())
    worst = pct.sort_values(ascending=False).head(worst_n)
    result["worst"] = [
        {"date": idx.isoformat(), "pct": float(val)} for idx, val in worst.items()
    ]
    return result


__all__ = ["cross_check_history"]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_data_check.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add data_check.py tests/test_data_check.py
git commit -m "feat(data_check): cross-provider close divergence utility"
```

---

### Task 7: Wire the API key into docker-compose without committing it

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.gitignore`

- [ ] **Step 1: Add `.env` to gitignore**

Append a line to `.gitignore` (do not reorder existing lines):

```
.env
```

- [ ] **Step 2: Add `env_file` to the service**

In `docker-compose.yml`, under the `backtest-lab` service, add a top-level key (sibling of `volumes:`):

```yaml
    env_file:
      - .env
```

- [ ] **Step 3: Document the expected key (manual, not committed)**

Tell the operator (this is a runtime step, not a code change): create `/root/apps/backtest-lab/.env` containing:

```
ALPHAVANTAGE_API_KEY=your_free_key_here
```

- [ ] **Step 4: Verify compose parses**

Run: `docker compose -f docker-compose.yml config >/dev/null && echo OK`
Expected: `OK` (no YAML/interpolation error). If `.env` does not yet exist, create an empty one first so compose does not warn.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml .gitignore
git commit -m "chore(alphavantage): load ALPHAVANTAGE_API_KEY via uncommitted .env"
```

---

### Task 8: Full test sweep + manual live smoke

**Files:** none (verification only)

- [ ] **Step 1: Run the whole suite**

Run: `python -m pytest -q`
Expected: all tests pass (existing suite + the new provider/data_check/metadata tests). If anything unrelated was already red in the dirty tree, note it but do not fix outside this plan's scope.

- [ ] **Step 2: One real daily call (operator, optional, costs 1 of 25/day)**

With a real key exported, confirm a live daily pull works end to end:

```bash
ALPHAVANTAGE_API_KEY=REALKEY python -c "from data_source import fetch_history; df,info=fetch_history('GBPJPY=X', provider='alphavantage'); print(info['source_note']); print(df.tail(3))"
```
Expected: a fresh fetch note and the last 3 daily GBPJPY bars. A second run within 12h should print `served from cache`.

- [ ] **Step 3: No commit** — verification task only.

---

## Self-Review Notes

- **Spec coverage:** provider (Tasks 1–5), symbol mapping (T2), error-as-200 (T3), per-endpoint schema incl. legacy crypto (T4), caching + guards + missing-key (T5), cross-check util (T6), `requests` dep (T1), compose env wiring (T7), fixture-based tests with no live CI calls (T2–T6), metadata test extension (T1). The `/api/datacheck` endpoint + dashboard panel are explicitly deferred in the spec — not in this plan.
- **Type consistency:** `_resolve_symbol` returns `(function, params, asset_class)` and is consumed that way in `fetch` (T5). `_extract_series` returns the series dict consumed by `_series_to_frame` → `ensure_ohlcv`. `cross_check_history` keys (`overlap_rows`, `max_abs_close_pct`, `bars_over_threshold`, `worst`) match between test (T6) and implementation (T6).
- **Shared-tree safety:** every commit is path-scoped to the files that task touches; no `git add -A`. New files only, plus single-line additions to `providers/__init__.py`, `requirements.txt`, `tests/test_providers_metadata.py`, `docker-compose.yml`, `.gitignore` — none under the chart-layer soft-lock.
