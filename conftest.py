"""Pytest bootstrap that makes the suite portable to any runner.

Two jobs:
  1. Put the repo root on sys.path so root modules (alpha_zoo, report, engine_*)
     import under a bare `pytest` invocation, not just `python -m pytest`.
  2. Skip-collect tests whose external resources are absent — the deep AZC tapes
     live in a sibling project on the host (AZC_FIXTURES), and a few lanes need
     optional broker SDKs. On CI those aren't present; rather than error at
     collection, we cleanly skip exactly those modules. Everything that runs on
     synthetic data (the report/publish/stats core) still runs and must pass.

Set AZC_NO_FIXTURES=1 to force the no-fixtures path locally and rehearse CI.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _fixtures_available() -> bool:
    if os.environ.get("AZC_NO_FIXTURES"):
        return False
    path = Path(os.environ.get("AZC_FIXTURES", "/root/apps/ict-autopilot/tests/fixtures"))
    try:
        return path.is_dir() and any(path.glob("*-Min60.json"))
    except OSError:
        return False


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


# Tests that load the real AZC/proven tapes (hardcode the fixture dir or pull
# assets through evolab.data). Without the tapes they have nothing to assert on.
_FIXTURE_TESTS = [
    "tests/test_bracket_signals.py",
    "tests/test_bracket_parity.py",
    "tests/test_sweep_overfit.py",
    "tests/test_evolab_data.py",
    "tests/test_evolab_search.py",
    "tests/test_evolab_fitness.py",
    "tests/test_evolab_universe.py",
    "tests/test_evolab_best_candidates.py",
    "tests/test_evolab_daemon.py",
    "tests/test_evolab_daemon_publish.py",
    "tests/test_lanes_perp_sim.py",
]

collect_ignore: list[str] = []

if not _fixtures_available():
    collect_ignore += _FIXTURE_TESTS
if not _module_available("alpaca"):
    collect_ignore += ["tests/test_execution_guard.py"]
if not _module_available("ib_async"):
    collect_ignore += ["tests/test_ibkr_futures.py"]
# storage.py (main-lab run store) is a separate working-tree module not carried
# on this branch; skip its test where the module isn't importable.
if not _module_available("storage"):
    collect_ignore += ["tests/test_runs_ingest.py"]
