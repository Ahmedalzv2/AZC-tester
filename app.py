from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from data_source import DataSourceError, available_providers, fetch_history
from engine import run_backtest
from jobs import run_in_pool, shutdown as shutdown_pool
from stats import significance
from storage import compare_runs, get_run, list_datasets, list_runs, save_dataset_access, save_run
from strategies import list_strategies
from sweep import run_sweep
from walkforward import walk_forward

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
API_TOKEN_ENV = "BACKTEST_LAB_API_TOKEN"
ENABLE_CUSTOM_PYTHON_ENV = "BACKTEST_LAB_ENABLE_CUSTOM_PYTHON"
PUBLIC_WRITE_LIMIT = int(os.environ.get("BACKTEST_LAB_PUBLIC_WRITE_LIMIT", "12"))
AUTH_WRITE_LIMIT = int(os.environ.get("BACKTEST_LAB_AUTH_WRITE_LIMIT", "120"))
RATE_WINDOW_SECONDS = int(os.environ.get("BACKTEST_LAB_RATE_WINDOW_SECONDS", "60"))
MAX_CUSTOM_CODE_CHARS = int(os.environ.get("BACKTEST_LAB_MAX_CUSTOM_CODE_CHARS", "12000"))
MAX_PARAM_JSON_CHARS = int(os.environ.get("BACKTEST_LAB_MAX_PARAM_JSON_CHARS", "12000"))
MAX_SWEEP_COMBOS = int(os.environ.get("BACKTEST_LAB_MAX_SWEEP_COMBOS", "500"))
RATE_BUCKETS: dict[str, list[float]] = {}

@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    # Tear down the compute pool so worker processes don't leak on restart.
    shutdown_pool()


app = FastAPI(title="Backtest Lab", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# EvoLab read-only dashboard (state-file reader; does NOT import the evolab pkg).
from evolab_api import router as evolab_router  # noqa: E402
app.include_router(evolab_router)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _api_token() -> str:
    return os.environ.get(API_TOKEN_ENV, "").strip()


def _token_configured() -> bool:
    return bool(_api_token())


def _request_token(request: Request) -> str:
    if request is None:
        return ""
    return request.headers.get("x-backtest-token", "").strip()


def _has_valid_token(request: Request) -> bool:
    token = _api_token()
    return bool(token) and _request_token(request) == token


def _custom_python_available(request: Request) -> bool:
    return _env_flag(ENABLE_CUSTOM_PYTHON_ENV, default=False) and _has_valid_token(request)


def _client_key(request: Request) -> str:
    if request is None:
        return "local-test"
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")


def _json_size(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":"), sort_keys=True, default=str))


def _enforce_write_access(request: Request) -> None:
    if _token_configured() and not _has_valid_token(request):
        raise HTTPException(status_code=401, detail="Missing or invalid X-Backtest-Token")

    limit = AUTH_WRITE_LIMIT if _has_valid_token(request) else PUBLIC_WRITE_LIMIT
    now = time.time()
    client_key = _client_key(request)
    bucket = RATE_BUCKETS.setdefault(client_key, [])
    cutoff = now - RATE_WINDOW_SECONDS
    bucket[:] = [stamp for stamp in bucket if stamp >= cutoff]
    if len(bucket) >= limit:
        raise HTTPException(status_code=429, detail=f"Rate limit hit: {limit} write requests per {RATE_WINDOW_SECONDS}s")
    bucket.append(now)


def _validate_research_request(request: Request, req: "BacktestRequest") -> None:
    if len((req.symbol or "").strip()) > 128:
        raise HTTPException(status_code=400, detail="symbol is too long")
    if req.file_path and len(req.file_path) > 4096:
        raise HTTPException(status_code=400, detail="file_path is too long")
    if _json_size(req.strategy_params) > MAX_PARAM_JSON_CHARS:
        raise HTTPException(status_code=400, detail=f"strategy_params is too large (>{MAX_PARAM_JSON_CHARS} chars)")
    if req.custom_code and len(req.custom_code) > MAX_CUSTOM_CODE_CHARS:
        raise HTTPException(status_code=400, detail=f"custom_code is too large (>{MAX_CUSTOM_CODE_CHARS} chars)")
    if req.custom_code and req.strategy != "custom_python":
        raise HTTPException(status_code=400, detail="custom_code is only allowed with the custom_python strategy")
    if req.strategy == "custom_python" and not _custom_python_available(request):
        raise HTTPException(status_code=403, detail="Custom Python is disabled on the public app")
    if req.custom_code and not _custom_python_available(request):
        raise HTTPException(status_code=403, detail="Custom Python is disabled on the public app")
    if isinstance(req, SweepRequest):
        combos = 1
        for values in req.grid.values():
            combos *= max(1, len(values))
        if combos > MAX_SWEEP_COMBOS:
            raise HTTPException(status_code=400, detail=f"Sweep grid is too large ({combos} combos > {MAX_SWEEP_COMBOS})")


def _guard_write_request(request: Request, req: "BacktestRequest | None" = None) -> None:
    _enforce_write_access(request)
    if req is not None:
        _validate_research_request(request, req)


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
    grid: dict[str, list[Any]] = Field(default_factory=dict)
    sort_by: str = Field(default="total_return_pct")
    iterations: int = Field(default=1000, ge=100, le=10_000)


class WalkForwardRequest(BacktestRequest):
    oos_fraction: float = Field(default=0.3, ge=0.05, le=0.95)
    iterations: int = Field(default=1000, ge=100, le=10_000)


class CompareRequest(BaseModel):
    run_ids: list[str] = Field(default_factory=list, min_length=1, max_length=12)


class IngestRequest(BaseModel):
    # A PRE-COMPUTED run (e.g. an EvoLab genome scored via simulate_signal).
    request_payload: dict[str, Any] = Field(default_factory=dict)
    response_payload: dict[str, Any] = Field(default_factory=dict)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "app": "backtest-lab",
        "write_token_required": _token_configured(),
        "custom_python_enabled": _env_flag(ENABLE_CUSTOM_PYTHON_ENV, default=False),
    }


@app.get("/api/config")
def config(request: Request = None) -> dict[str, Any]:
    return {
        "write_token_required": _token_configured(),
        "custom_python_enabled": _env_flag(ENABLE_CUSTOM_PYTHON_ENV, default=False),
        "custom_python_available": _custom_python_available(request),
        "public_write_limit": PUBLIC_WRITE_LIMIT,
        "authenticated_write_limit": AUTH_WRITE_LIMIT,
        "rate_window_seconds": RATE_WINDOW_SECONDS,
    }


@app.get("/api/strategies")
def strategies(request: Request = None) -> dict[str, Any]:
    return list_strategies(include_custom=_custom_python_available(request))


@app.get("/api/providers")
def providers() -> dict[str, Any]:
    return available_providers()


@app.get("/api/live-significance")
def live_significance_endpoint() -> dict[str, Any]:
    # Forward-test verdict from the AZC shadow lanes — the un-overfittable t-stat
    # that accrues from trades taken after the strategy was frozen.
    from live_significance import live_significance

    return live_significance()


@app.get("/api/hunt")
def hunt_endpoint() -> dict[str, Any]:
    # Latest disciplined strategy-search run: trials, Bonferroni-deflated bar,
    # OOS-validated candidates, and the top configs by out-of-sample t-stat.
    import json as _json
    from pathlib import Path as _P

    results = _P(__file__).resolve().parent / "hunt-results.jsonl"
    if not results.exists():
        return {"status": "no hunt has run yet", "runs": 0}
    lines = [ln for ln in results.read_text().splitlines() if ln.strip()]
    latest = _json.loads(lines[-1]) if lines else {}
    return {"runs": len(lines), "latest": latest}


@app.get("/api/runs")
def runs(limit: int = 50) -> dict[str, Any]:
    safe_limit = max(1, min(limit, 200))
    return {"count": safe_limit, "runs": list_runs(limit=safe_limit)}


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str) -> dict[str, Any]:
    record = get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Unknown run: {run_id}")
    return record


@app.post("/api/runs/ingest")
def ingest_run(req: IngestRequest, request: Request = None) -> dict[str, Any]:
    # Persists a pre-computed run; never executes strategy code (stores the
    # supplied payload only). Keeps the API process the single store writer.
    _enforce_write_access(request)
    run_type = str(req.request_payload.get("run_type") or "backtest")
    run_id = save_run(run_type, req.request_payload, req.response_payload)
    return {"run_id": run_id}


@app.get("/api/datasets")
def datasets(limit: int = 50) -> dict[str, Any]:
    safe_limit = max(1, min(limit, 200))
    rows = list_datasets(limit=safe_limit)
    return {"count": len(rows), "datasets": rows}


@app.post("/api/compare")
def compare_endpoint(req: CompareRequest, request: Request = None) -> dict[str, Any]:
    _enforce_write_access(request)
    out = compare_runs(req.run_ids)
    if out["count"] == 0:
        raise HTTPException(status_code=404, detail="None of the requested run_ids were found")
    return out


@app.post("/api/backtest")
def backtest(req: BacktestRequest, request: Request = None) -> dict[str, Any]:
    _guard_write_request(request, req)
    try:
        request_payload = _model_to_dict(req)
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
        _store_dataset(request_payload, source_info)
        result = run_in_pool(
            run_backtest,
            df=df,
            strategy_name=req.strategy,
            params=req.strategy_params,
            initial_cash=req.initial_cash,
            fee_bps=req.fee_bps,
            custom_code=req.custom_code,
            interval=req.interval,
        )
        payload = {
            "metrics": result.metrics,
            "curve": result.curve,
            "trades": result.trades,
            "price_bars": _price_bars(df),
            "source": source_info,
            "significance": result.metrics.get("significance") or significance(result.curve),
            "custom_code": req.custom_code or "",
        }
        return _persist_response("backtest", request_payload, payload)
    except (ValueError, DataSourceError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/sweep")
def sweep_endpoint(req: SweepRequest, request: Request = None) -> dict[str, Any]:
    _guard_write_request(request, req)
    try:
        request_payload = _model_to_dict(req)
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
        _store_dataset(request_payload, source_info)
        out = run_in_pool(
            run_sweep,
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
        return _persist_response("sweep", request_payload, out)
    except (ValueError, DataSourceError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/walkforward")
def walkforward_endpoint(req: WalkForwardRequest, request: Request = None) -> dict[str, Any]:
    _guard_write_request(request, req)
    try:
        request_payload = _model_to_dict(req)
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
        _store_dataset(request_payload, source_info)
        out = run_in_pool(
            walk_forward,
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
        return _persist_response("walkforward", request_payload, out)
    except (ValueError, DataSourceError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/example/custom-strategy")
def custom_strategy_example(request: Request = None) -> dict[str, str]:
    if not _custom_python_available(request):
        raise HTTPException(status_code=403, detail="Custom Python is disabled on the public app")
    example = """def build_signals(df, params):
    fast = int(params.get('fast', 10))
    slow = int(params.get('slow', 30))
    momentum = df['Close'].pct_change(fast)
    trend = df['Close'].rolling(slow).mean()
    position = ((momentum > 0) & (df['Close'] > trend)).astype(float)
    return position
"""
    return {"code": example}


def _model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _price_bars(df) -> list[dict[str, Any]]:
    return [
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


def _persist_response(run_type: str, request_payload: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    response = dict(payload)
    try:
        response["run_id"] = save_run(run_type, request_payload, response)
    except Exception as exc:
        response["run_id"] = ""
        response["storage_error"] = str(exc)
    return response


def _store_dataset(request_payload: dict[str, Any], source_info: dict[str, Any]) -> None:
    try:
        save_dataset_access(request_payload, source_info)
    except Exception:
        # Dataset logging should not block the research run.
        return
