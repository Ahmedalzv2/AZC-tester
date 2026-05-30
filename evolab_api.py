"""Read-only EvoLab dashboard API.

Deliberately decoupled from the `evolab` package: it only READS the JSON state
files the search/daemon write, so the web app never imports `bracket_signals`
(untracked) and stays pushable. Serves the standalone /evolab page too.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

router = APIRouter()

# Overridable in tests.
EVOLAB_STATE_DIR = Path(__file__).resolve().parent / "evolab" / "state"
STATIC_DIR = Path(__file__).resolve().parent / "static"
_RESERVED = {"trials.json", "daemon.json"}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _latest_run_by_asset(state_dir: Path) -> dict[str, dict]:
    """Last audit record per asset from runs.jsonl (best_is_score, ts, etc.)."""
    runs_path = state_dir / "runs.jsonl"  # Store writes it inside the state dir
    out: dict[str, dict] = {}
    try:
        for line in runs_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            asset = rec.get("asset")
            if asset:
                out[asset] = rec  # later lines overwrite -> last wins
    except OSError:
        pass
    return out


def evolab_state(state_dir: Path | None = None) -> dict[str, Any]:
    state_dir = state_dir or EVOLAB_STATE_DIR
    trials = _read_json(state_dir / "trials.json") or {}
    cumulative = int(trials.get("cumulative", 0))
    daemon = _read_json(state_dir / "daemon.json")  # None until the daemon runs
    latest = _latest_run_by_asset(state_dir)

    assets = []
    if state_dir.exists():
        for path in sorted(state_dir.glob("*.json")):
            if path.name in _RESERVED:
                continue
            st = _read_json(path)
            if not isinstance(st, dict):
                continue
            run = latest.get(st.get("asset"), {})
            assets.append({
                "asset": st.get("asset", path.stem),
                "generation": st.get("generation", 0),
                "champion": st.get("champion"),  # None = honest null
                "best_is_score": run.get("best_is_score"),
                "last_run_ts": run.get("ts"),
            })

    return {
        "cumulative_trials": cumulative,
        "alpha_deflated": 0.05 / max(1, cumulative),
        "daemon": daemon,  # null until Phase-2 daemon is running
        "assets": assets,
    }


@router.get("/api/evolab")
def get_evolab() -> dict[str, Any]:
    return evolab_state()


@router.get("/evolab")
def evolab_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "evolab.html")


# ── strategy-testing gateway (AZC submits a strategy → honest verdict) ────────
class VerdictRequest(BaseModel):
    family: str = Field(..., description="strategy family, e.g. donchian_break (azc_trend) / donchian_fade (azc_meanrev)")
    params: dict = Field(default_factory=dict, description="family params, e.g. {don, atrN, atrMult, trail, erMin, regimeN}")
    asset: str = Field(..., description="crypto-perp with mounted tape, e.g. SOL/DOGE/XRP")
    oos_fraction: float = Field(default=0.30, ge=0.05, le=0.95)


@router.post("/api/evolab/verdict")
def post_verdict(req: VerdictRequest) -> dict:
    """Run a submitted strategy through the fee-accurate truth layer once and
    return an honest real/marginal/noise verdict. Engine deps are imported
    lazily so this module (and the read-only dashboard) stay import-clean."""
    try:
        from evolab import data, fitness  # local-only deps (bracket_signals)
    except Exception as exc:  # engine not available on this host
        raise HTTPException(status_code=503, detail=f"EvoLab engine unavailable: {exc}")

    if req.asset not in data.available_assets():
        raise HTTPException(
            status_code=400,
            detail=f"unknown/unmounted asset '{req.asset}'. Available: {data.available_assets()}",
        )
    try:
        bars = data.load_asset(req.asset)
        is_bars, oos_bars = data.split(bars, oos_fraction=req.oos_fraction)
        result = fitness.assess(req.family, req.params, is_bars, oos_bars)
    except ValueError as exc:  # bad family / params
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"strategy failed to run: {exc}")
    result["asset"] = req.asset
    return result
