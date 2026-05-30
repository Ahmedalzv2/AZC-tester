from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from data_source import DataSourceError, available_providers, fetch_history
from engine import run_backtest
from stats import significance
from strategies import list_strategies
from sweep import run_sweep

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

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


class SweepRequest(BacktestRequest):
    # Maps param name -> list of values to grid over, e.g. {"fast": [5, 10]}.
    grid: dict[str, list[Any]] = Field(default_factory=dict)
    sort_by: str = Field(default="total_return_pct")
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


@app.post("/api/backtest")
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
        return {
            "metrics": result.metrics,
            "curve": result.curve,
            "trades": result.trades,
            "price_bars": latest_bars,
            "source": source_info,
            "significance": result.metrics.get("significance") or significance(result.curve),
            "custom_code": req.custom_code or "",
        }
    except (ValueError, DataSourceError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/sweep")
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
