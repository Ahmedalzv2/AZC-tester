from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

import duckdb

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "storage" / "backtest_lab.duckdb"
_DB_LOCK = Lock()


def db_path() -> Path:
    path = Path(os.environ.get("BACKTEST_LAB_DB", str(DEFAULT_DB_PATH))).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(str(db_path()))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            id VARCHAR PRIMARY KEY,
            created_at TIMESTAMP,
            run_type VARCHAR,
            title VARCHAR,
            strategy VARCHAR,
            provider VARCHAR,
            symbol VARCHAR,
            interval VARCHAR,
            years INTEGER,
            market VARCHAR,
            timezone VARCHAR,
            session VARCHAR,
            params_json TEXT,
            request_json TEXT,
            metrics_json TEXT,
            significance_json TEXT,
            source_json TEXT,
            result_json TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS datasets (
            id VARCHAR PRIMARY KEY,
            created_at TIMESTAMP,
            provider VARCHAR,
            symbol VARCHAR,
            interval VARCHAR,
            years INTEGER,
            market VARCHAR,
            timezone VARCHAR,
            session VARCHAR,
            file_path VARCHAR,
            rows INTEGER,
            start_at TIMESTAMP,
            end_at TIMESTAMP,
            source_note VARCHAR,
            source_json TEXT,
            dataset_json TEXT
        )
        """
    )
    return conn


def _dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _load(payload: str | None) -> Any:
    if not payload:
        return None
    return json.loads(payload)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _pick_preview(run_type: str, response_payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if run_type == "backtest":
        return response_payload.get("metrics") or {}, response_payload.get("significance") or {}
    if run_type == "walkforward":
        out_sample = response_payload.get("out_sample") or {}
        return out_sample.get("metrics") or {}, out_sample.get("significance") or {}
    if run_type == "sweep":
        best = response_payload.get("best") or {}
        return best.get("metrics") or {}, best.get("significance") or {}
    return {}, {}


def _request_params(request_payload: dict[str, Any]) -> dict[str, Any]:
    return request_payload.get("strategy_params") or {}


def _title(request_payload: dict[str, Any], run_type: str) -> str:
    strategy = request_payload.get("strategy") or "unknown"
    symbol = request_payload.get("symbol") or "?"
    interval = request_payload.get("interval") or "?"
    return f"{run_type}:{strategy}:{symbol}:{interval}"


def save_dataset_access(request_payload: dict[str, Any], source_payload: dict[str, Any]) -> str:
    dataset = source_payload.get("dataset") or {}
    record_id = uuid.uuid4().hex[:12]
    start_at = _iso(dataset.get("start"))
    end_at = _iso(dataset.get("end"))
    with _DB_LOCK:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO datasets (
                    id, created_at, provider, symbol, interval, years, market,
                    timezone, session, file_path, rows, start_at, end_at,
                    source_note, source_json, dataset_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    record_id,
                    _now(),
                    request_payload.get("data_provider") or source_payload.get("provider") or "",
                    request_payload.get("symbol") or source_payload.get("symbol") or "",
                    request_payload.get("interval") or source_payload.get("interval") or "",
                    int(request_payload.get("years") or 0),
                    request_payload.get("market") or dataset.get("market") or "",
                    request_payload.get("timezone") or dataset.get("timezone") or "UTC",
                    request_payload.get("session") or dataset.get("session") or "",
                    request_payload.get("file_path") or source_payload.get("file_path") or "",
                    int(dataset.get("rows") or 0),
                    start_at,
                    end_at,
                    source_payload.get("source_note") or "",
                    _dump(source_payload),
                    _dump(dataset),
                ],
            )
        finally:
            conn.close()
    return record_id


def save_run(run_type: str, request_payload: dict[str, Any], response_payload: dict[str, Any]) -> str:
    run_id = uuid.uuid4().hex[:12]
    metrics, significance = _pick_preview(run_type, response_payload)
    with _DB_LOCK:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO runs (
                    id, created_at, run_type, title, strategy, provider, symbol,
                    interval, years, market, timezone, session, params_json,
                    request_json, metrics_json, significance_json, source_json, result_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    run_id,
                    _now(),
                    run_type,
                    _title(request_payload, run_type),
                    request_payload.get("strategy") or "",
                    request_payload.get("data_provider") or "",
                    request_payload.get("symbol") or "",
                    request_payload.get("interval") or "",
                    int(request_payload.get("years") or 0),
                    request_payload.get("market") or "",
                    request_payload.get("timezone") or "UTC",
                    request_payload.get("session") or "",
                    _dump(_request_params(request_payload)),
                    _dump(request_payload),
                    _dump(metrics),
                    _dump(significance),
                    _dump(response_payload.get("source") or {}),
                    _dump(response_payload),
                ],
            )
        finally:
            conn.close()
    return run_id


def list_runs(limit: int = 50) -> list[dict[str, Any]]:
    with _DB_LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                """
                SELECT id, created_at, run_type, title, strategy, provider, symbol,
                       interval, years, market, timezone, session, params_json,
                       metrics_json, significance_json, source_json
                FROM runs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                [limit],
            ).fetchall()
        finally:
            conn.close()
    out = []
    for row in rows:
        out.append(
            {
                "id": row[0],
                "created_at": _iso(row[1]),
                "run_type": row[2],
                "title": row[3],
                "strategy": row[4],
                "provider": row[5],
                "symbol": row[6],
                "interval": row[7],
                "years": row[8],
                "market": row[9],
                "timezone": row[10],
                "session": row[11],
                "params": _load(row[12]) or {},
                "metrics": _load(row[13]) or {},
                "significance": _load(row[14]) or {},
                "source": _load(row[15]) or {},
            }
        )
    return out


def list_datasets(limit: int = 50) -> list[dict[str, Any]]:
    with _DB_LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                """
                SELECT id, created_at, provider, symbol, interval, years, market,
                       timezone, session, file_path, rows, start_at, end_at,
                       source_note, source_json, dataset_json
                FROM datasets
                ORDER BY created_at DESC
                LIMIT ?
                """,
                [limit],
            ).fetchall()
        finally:
            conn.close()
    out = []
    for row in rows:
        out.append(
            {
                "id": row[0],
                "created_at": _iso(row[1]),
                "provider": row[2],
                "symbol": row[3],
                "interval": row[4],
                "years": row[5],
                "market": row[6],
                "timezone": row[7],
                "session": row[8],
                "file_path": row[9],
                "rows": row[10],
                "start": _iso(row[11]),
                "end": _iso(row[12]),
                "source_note": row[13],
                "source": _load(row[14]) or {},
                "dataset": _load(row[15]) or {},
            }
        )
    return out


def get_run(run_id: str) -> dict[str, Any] | None:
    with _DB_LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                """
                SELECT id, created_at, run_type, title, strategy, provider, symbol,
                       interval, years, market, timezone, session, params_json,
                       request_json, metrics_json, significance_json, source_json, result_json
                FROM runs
                WHERE id = ?
                """,
                [run_id],
            ).fetchone()
        finally:
            conn.close()
    if row is None:
        return None
    return {
        "id": row[0],
        "created_at": _iso(row[1]),
        "run_type": row[2],
        "title": row[3],
        "strategy": row[4],
        "provider": row[5],
        "symbol": row[6],
        "interval": row[7],
        "years": row[8],
        "market": row[9],
        "timezone": row[10],
        "session": row[11],
        "params": _load(row[12]) or {},
        "request": _load(row[13]) or {},
        "metrics": _load(row[14]) or {},
        "significance": _load(row[15]) or {},
        "source": _load(row[16]) or {},
        "result": _load(row[17]) or {},
    }


def compare_runs(run_ids: list[str]) -> dict[str, Any]:
    runs = []
    for run_id in run_ids:
        run = get_run(run_id)
        if run is not None:
            runs.append(run)
    comparisons = []
    chart_series = []
    for run in runs:
        metrics = run.get("metrics") or {}
        significance = run.get("significance") or {}
        result = run.get("result") or {}
        curve = result.get("curve") or []
        comparisons.append(
            {
                "id": run["id"],
                "created_at": run["created_at"],
                "run_type": run["run_type"],
                "title": run["title"],
                "strategy": run["strategy"],
                "provider": run["provider"],
                "symbol": run["symbol"],
                "interval": run["interval"],
                "metrics": metrics,
                "significance": significance,
            }
        )
        if curve:
            first_equity = float(curve[0].get("equity") or 0.0) or 1.0
            chart_series.append(
                {
                    "id": run["id"],
                    "label": f"{run['strategy']} {run['symbol']} {run['interval']}",
                    "curve": [
                        {
                            "time": row.get("time"),
                            "equity": row.get("equity"),
                            "normalized": round((float(row.get("equity") or 0.0) / first_equity) * 100, 3),
                        }
                        for row in curve[-400:]
                    ],
                }
            )
    return {
        "count": len(comparisons),
        "runs": comparisons,
        "chart_series": chart_series,
    }
