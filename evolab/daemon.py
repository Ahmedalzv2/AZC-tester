"""EvoLab daemon: a gentle, always-on, round-robin strategy search.

Visits each crypto-perp asset in turn, evolves it a few generations (resuming
its persisted population), writes a heartbeat, then sleeps. Single-process (one
asset at a time) so there are no parallel writers — the dashboard reads the
atomically-written state files. Run via systemd, nice'd. Tunable by env:

  EVOLAB_GENS_PER_VISIT (default 3)
  EVOLAB_SLEEP_SECONDS  (default 30)
  EVOLAB_POP            (default 24)

The loop body is factored into one_cycle() so tests can run bounded cycles
without an infinite loop.
"""
from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

from evolab import data
from evolab.search import STATE_DIR, run_search
from evolab.store import Store, write_json_atomic

GENS_PER_VISIT = int(os.environ.get("EVOLAB_GENS_PER_VISIT", "3"))
SLEEP_SECONDS = int(os.environ.get("EVOLAB_SLEEP_SECONDS", "30"))
POP = int(os.environ.get("EVOLAB_POP", "24"))

_stop = False


def _request_stop(*_: Any) -> None:
    global _stop
    _stop = True


def resolve_assets() -> list[str]:
    """Which assets the daemon searches. Default = every mounted tape
    (data.available_assets, now the full 25-symbol basket). An explicit
    EVOLAB_ASSETS="SOL,SUI,XRP" env var overrides to a scoped subset, keeping
    only entries that actually have a fixture mounted (silently drops typos)."""
    override = os.environ.get("EVOLAB_ASSETS", "").strip()
    if not override:
        return data.available_assets()
    mounted = set(data.available_assets())
    want = [a.strip().upper() for a in override.split(",") if a.strip()]
    return [a for a in want if a in mounted]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _write_heartbeat(state_dir: Path, cycle: int, last_asset: str) -> None:
    write_json_atomic(state_dir / "daemon.json", {
        "last_cycle_ts": _now_ms(),
        "cycle": cycle,
        "last_asset": last_asset,
        "pid": os.getpid(),
        "gens_per_visit": GENS_PER_VISIT,
        "sleep_seconds": SLEEP_SECONDS,
    })


def one_cycle(
    assets: list[str],
    bars_cache: dict[str, list],
    store: Store,
    *,
    cycle: int,
    gens: int = GENS_PER_VISIT,
    pop: int = POP,
    state_dir: Path | None = None,
) -> list[str]:
    """Evolve every asset once. A failing asset is logged and skipped, never
    aborts the cycle. Returns the assets that advanced this cycle."""
    state_dir = state_dir or store.base
    advanced: list[str] = []
    for asset in assets:
        try:
            bars = bars_cache.get(asset)
            if bars is None:
                bars = bars_cache[asset] = data.load_asset(asset)
            result = run_search(
                asset, bars, generations=gens, pop_size=pop,
                seed=cycle, store=store, ts=_now_ms(),
            )
            advanced.append(asset)
            champ = result.get("champion")
            print(f"[evolab] cycle={cycle} {asset} gen={result['generation']} "
                  f"trials={result['trials_cumulative']} bestIS={result['best_is_score']} "
                  f"champion={'YES ' + champ['family'] if champ else 'none'}", flush=True)
            _write_heartbeat(state_dir, cycle, asset)
        except Exception as err:  # one bad asset must not kill the loop
            print(f"[evolab] cycle={cycle} {asset} ERROR: {err!r} — skipped", flush=True)
    return advanced


def run_daemon() -> int:
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    assets = resolve_assets()
    if not assets:
        print("[evolab] no assets to search (no fixtures mounted, or EVOLAB_ASSETS matched none); exiting", flush=True)
        return 1

    store = Store(STATE_DIR)
    bars_cache: dict[str, list] = {}
    print(f"[evolab] daemon up: assets={assets} gens/visit={GENS_PER_VISIT} "
          f"sleep={SLEEP_SECONDS}s pop={POP}", flush=True)

    cycle = 0
    while not _stop:
        cycle += 1
        one_cycle(assets, bars_cache, store, cycle=cycle)
        # Sleep in short slices so SIGTERM is honoured promptly.
        slept = 0
        while slept < SLEEP_SECONDS and not _stop:
            time.sleep(min(2, SLEEP_SECONDS - slept))
            slept += 2

    print("[evolab] SIGTERM received — clean shutdown", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(run_daemon())
