from __future__ import annotations

import hmac
import os
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from data_source import DataSourceError, available_providers, fetch_history
from engine import run_backtest
from runs_store import delete_run, get_run, list_runs, save_run
from stats import significance
from strategies import list_strategies
from sweep import run_sweep
from walkforward import walk_forward

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# Shared-secret gate for the compute/mutating endpoints. The endpoints that run
# strategy code (/api/backtest, /api/sweep, /api/walkforward) and the destructive
# delete are protected when AZC_API_KEY is set; reads and the static UI stay open.
# If AZC_API_KEY is unset (e.g. local dev) auth is disabled — set it in any
# internet-facing deploy, since custom_python executes arbitrary Python.
API_KEY = os.environ.get("AZC_API_KEY", "").strip()


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if not API_KEY:
        return  # auth disabled when no key is configured
    if not x_api_key or not hmac.compare_digest(x_api_key, API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing API key (send header X-API-Key)")


app = FastAPI(title="Backtest Lab")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class BacktestRequest(BaseModel):
    data_provider: str = Field(default="yahoo")
    symbol: str = Field(default="SPY")
    interval: str = Field(default="1d")
    years: int = Field(default=5, ge=1, le=10)
    refresh_data: bool = False
    file_path: str | None = None
    market: str | None = None
    timezone: str = Field(default="UTC")
    session: str | None = None
    strategy: str = Field(default="sma_cross")
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    initial_cash: float = Field(default=10_000, gt=0)
    fee_bps: float = Field(default=10, ge=0)
    custom_code: str | None = None
    # AZC-assigned strategy name + optional tags, so the platform can read its
    # own strategy back by name via GET /api/runs?label=...
    label: str | None = None
    tags: list[str] = Field(default_factory=list)


class SweepRequest(BacktestRequest):
    # Maps param name -> list of values to grid over, e.g. {"fast": [5, 10]}.
    grid: dict[str, list[Any]] = Field(default_factory=dict)
    sort_by: str = Field(default="total_return_pct")
    iterations: int = Field(default=1000, ge=100, le=10_000)


class WalkForwardRequest(BacktestRequest):
    # Fraction of the most-recent bars held out as out-of-sample.
    oos_fraction: float = Field(default=0.3, ge=0.05, le=0.95)
    iterations: int = Field(default=1000, ge=100, le=10_000)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "app": "backtest-lab"}


@app.get("/api/strategies")
def strategies() -> dict[str, Any]:
    return list_strategies()


@app.get("/api/providers")
def providers() -> dict[str, Any]:
    return available_providers()


@app.post("/api/backtest", dependencies=[Depends(require_api_key)])
def backtest(req: BacktestRequest) -> dict[str, Any]:
    try:
        df, source_info = fetch_history(
            symbol=req.symbol.strip(),
            interval=req.interval,
            years=req.years,
            refresh=req.refresh_data,
            provider=req.data_provider,
            file_path=req.file_path,
            market=req.market,
            timezone=req.timezone,
            session=req.session,
        )
        result = run_backtest(
            df=df,
            strategy_name=req.strategy,
            params=req.strategy_params,
            initial_cash=req.initial_cash,
            fee_bps=req.fee_bps,
            custom_code=req.custom_code,
            interval=req.interval,
        )
        latest_bars = [
            {
                "time": idx.isoformat(),
                "open": round(float(row["Open"]), 4),
                "high": round(float(row["High"]), 4),
                "low": round(float(row["Low"]), 4),
                "close": round(float(row["Close"]), 4),
                "volume": round(float(row.get("Volume", 0.0)), 4),
            }
            for idx, row in df.tail(400).iterrows()
        ]
        response = {
            "metrics": result.metrics,
            "curve": result.curve,
            "trades": result.trades,
            "price_bars": latest_bars,
            "source": source_info,
            "significance": result.metrics.get("significance") or significance(result.curve),
            "custom_code": req.custom_code or "",
        }
        # Every successful run is saved automatically — research is never lost.
        try:
            response["saved"] = save_run(req.model_dump(), response)
        except Exception:  # persistence must never break a backtest
            response["saved"] = None
        return response
    except (ValueError, DataSourceError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/runs")
def runs(label: str | None = None, symbol: str | None = None, strategy: str | None = None) -> dict[str, Any]:
    # AZC reads its strategies back by the name it assigned: GET /api/runs?label=...
    return {"runs": list_runs(label=label, symbol=symbol, strategy=strategy)}


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str) -> dict[str, Any]:
    record = get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return record


@app.delete("/api/runs/{run_id}", dependencies=[Depends(require_api_key)])
def run_delete(run_id: str) -> dict[str, Any]:
    return {"deleted": delete_run(run_id)}


class IngestRequest(BaseModel):
    # A PRE-COMPUTED run promoted from the lab (e.g. an EvoLab champion scored
    # via simulate_signal). Stored as-is; no strategy code is executed here.
    request_payload: dict[str, Any] = Field(default_factory=dict)
    response_payload: dict[str, Any] = Field(default_factory=dict)


@app.post("/api/runs/ingest", dependencies=[Depends(require_api_key)])
def ingest_run(req: IngestRequest) -> dict[str, Any]:
    return {"saved": save_run(req.request_payload, req.response_payload)}


@app.post("/api/sweep", dependencies=[Depends(require_api_key)])
def sweep_endpoint(req: SweepRequest) -> dict[str, Any]:
    try:
        df, source_info = fetch_history(
            symbol=req.symbol.strip(),
            interval=req.interval,
            years=req.years,
            refresh=req.refresh_data,
            provider=req.data_provider,
            file_path=req.file_path,
            market=req.market,
            timezone=req.timezone,
            session=req.session,
        )
        out = run_sweep(
            df=df,
            strategy_name=req.strategy,
            grid=req.grid,
            base_params=req.strategy_params,
            initial_cash=req.initial_cash,
            fee_bps=req.fee_bps,
            custom_code=req.custom_code,
            interval=req.interval,
            sort_by=req.sort_by,
            iterations=req.iterations,
        )
        out["source"] = source_info
        return out
    except (ValueError, DataSourceError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/walkforward", dependencies=[Depends(require_api_key)])
def walkforward_endpoint(req: WalkForwardRequest) -> dict[str, Any]:
    try:
        df, source_info = fetch_history(
            symbol=req.symbol.strip(),
            interval=req.interval,
            years=req.years,
            refresh=req.refresh_data,
            provider=req.data_provider,
            file_path=req.file_path,
            market=req.market,
            timezone=req.timezone,
            session=req.session,
        )
        out = walk_forward(
            df=df,
            strategy_name=req.strategy,
            params=req.strategy_params,
            oos_fraction=req.oos_fraction,
            initial_cash=req.initial_cash,
            fee_bps=req.fee_bps,
            custom_code=req.custom_code,
            interval=req.interval,
            iterations=req.iterations,
        )
        out["source"] = source_info
        return out
    except (ValueError, DataSourceError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/example/custom-strategy")
def custom_strategy_example() -> dict[str, str]:
    example = """def build_signals(df, params):
    fast = int(params.get('fast', 10))
    slow = int(params.get('slow', 30))
    momentum = df['Close'].pct_change(fast)
    trend = df['Close'].rolling(slow).mean()
    position = ((momentum > 0) & (df['Close'] > trend)).astype(float)
    return position
"""
    return {"code": example}
