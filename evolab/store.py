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
