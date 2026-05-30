"""Persistence: global cumulative trial counter (deflation), per-asset state
(population + champion), and an append-only audit log.

The trial counter is the honest-accounting heart: alpha_deflated = 0.05 /
cumulative_trials, so the significance bar tightens for the whole life of the
search, not per run.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evolab.genome import Genome


class Store:
    def __init__(self, base_dir: Path):
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)
        self._trials_path = self.base / "trials.json"
        self._runs_path = self.base / "runs.jsonl"

    # ── cumulative trial counter ──────────────────────────────────────────
    def cumulative_trials(self) -> int:
        if not self._trials_path.exists():
            return 0
        try:
            return int(json.loads(self._trials_path.read_text()).get("cumulative", 0))
        except (json.JSONDecodeError, ValueError):
            return 0

    def bump_trials(self, n: int) -> int:
        total = self.cumulative_trials() + int(n)
        self._trials_path.write_text(json.dumps({"cumulative": total}))
        return total

    def alpha_deflated(self) -> float:
        return 0.05 / max(1, self.cumulative_trials())

    # ── per-asset state ───────────────────────────────────────────────────
    def _state_path(self, asset: str) -> Path:
        return self.base / f"{asset}.json"

    def load_state(self, asset: str) -> dict[str, Any]:
        path = self._state_path(asset)
        if not path.exists():
            return {"asset": asset, "generation": 0, "population": [], "champion": None}
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return {"asset": asset, "generation": 0, "population": [], "champion": None}

    def save_state(self, asset: str, state: dict[str, Any]) -> None:
        self._state_path(asset).write_text(json.dumps(state))

    # ── audit log ─────────────────────────────────────────────────────────
    def append_run(self, record: dict[str, Any]) -> None:
        with self._runs_path.open("a") as f:
            f.write(json.dumps(record) + "\n")


def genome_to_dict(g: Genome) -> dict[str, Any]:
    return {"family": g.family, "params": g.params}


def genome_from_dict(d: dict[str, Any]) -> Genome:
    return Genome(d["family"], dict(d["params"]))
