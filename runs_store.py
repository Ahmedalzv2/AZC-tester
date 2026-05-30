"""Automatic backtest run history.

Every successful `/api/backtest` is saved here so research is never lost — no
save button, no manual step. Each run is one JSON file under `runs/` holding the
full report response (so it can be re-opened exactly as it was), plus a light
summary appended to `runs/index.json` for fast listing.

This is deliberately a flat local store, not a database: it is inspectable by
hand, trivially backed up, and disposable (the whole dir is gitignored). Good
enough for a single-researcher lab; swap for SQLite if it ever outgrows that.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

BASE_DIR = Path(__file__).resolve().parent
RUNS_DIR = BASE_DIR / "runs"
INDEX_PATH = RUNS_DIR / "index.json"
MAX_INDEX = 500  # keep the listing snappy; full files are never auto-deleted


def _ensure_dir() -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)


def _load_index() -> list[dict[str, Any]]:
    if not INDEX_PATH.exists():
        return []
    try:
        return json.loads(INDEX_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _write_index(entries: list[dict[str, Any]]) -> None:
    INDEX_PATH.write_text(json.dumps(entries, indent=2))


def _spark(response: dict[str, Any], points: int = 48) -> list[float]:
    """Downsampled equity curve for the Browse card sparkline."""
    curve = response.get("curve") or []
    equity = [float(p.get("equity", 0.0)) for p in curve]
    n = len(equity)
    if n <= points:
        return [round(e, 2) for e in equity]
    step = n / points
    return [round(equity[min(int(i * step), n - 1)], 2) for i in range(points)]


def _summary(run_id: str, created_at: float, request: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    metrics = response.get("metrics", {}) or {}
    report = metrics.get("report", {}) or {}
    source = response.get("source", {}) or {}
    return {
        "id": run_id,
        "created_at": created_at,
        "symbol": source.get("symbol") or request.get("symbol"),
        "interval": metrics.get("interval") or request.get("interval"),
        "strategy": metrics.get("strategy") or request.get("strategy"),
        "params": metrics.get("strategy_params") or request.get("strategy_params") or {},
        "total_return_pct": metrics.get("total_return_pct"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "win_rate_pct": metrics.get("win_rate_pct"),
        "trade_count": metrics.get("trade_count"),
        "net_pnl": report.get("net_pnl"),
        "profit_factor": report.get("profit_factor"),
        "significant": (response.get("significance") or {}).get("significant"),
        "label": request.get("label"),
        "tags": request.get("tags") or [],
        "spark": _spark(response),
    }


def save_run(request: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    """Persist a backtest response and return its index summary."""
    _ensure_dir()
    run_id = f"{int(time.time() * 1000)}-{uuid4().hex[:6]}"
    created_at = time.time()

    record = {"id": run_id, "created_at": created_at, "request": request, "response": response}
    (RUNS_DIR / f"{run_id}.json").write_text(json.dumps(record))

    summary = _summary(run_id, created_at, request, response)
    index = _load_index()
    index.insert(0, summary)  # newest first
    _write_index(index[:MAX_INDEX])
    return summary


def list_runs(label: str | None = None, symbol: str | None = None, strategy: str | None = None) -> list[dict[str, Any]]:
    """Saved-run summaries, newest first, optionally filtered (for AZC read-back)."""
    entries = _load_index()
    if label:
        entries = [e for e in entries if (e.get("label") or "").lower() == label.lower()]
    if symbol:
        entries = [e for e in entries if e.get("symbol") == symbol]
    if strategy:
        entries = [e for e in entries if e.get("strategy") == strategy]
    return entries


def get_run(run_id: str) -> dict[str, Any] | None:
    path = RUNS_DIR / f"{run_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def delete_run(run_id: str) -> bool:
    path = RUNS_DIR / f"{run_id}.json"
    existed = path.exists()
    if existed:
        path.unlink()
    index = [entry for entry in _load_index() if entry.get("id") != run_id]
    _write_index(index)
    return existed
