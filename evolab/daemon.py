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

from evolab import data, proposer
from evolab.search import STATE_DIR, run_search
from evolab.store import Store, write_json_atomic
from evolab.genome import Genome
from evolab.publish import publish_genome
import json as _json

PUBLISH_URL = os.environ.get("EVOLAB_PUBLISH_URL", "https://backtest-gallant.srv1688368.hstgr.cloud")


def _publish_key() -> str | None:
    key = os.environ.get("EVOLAB_PUBLISH_KEY", "").strip()
    if key:
        return key
    env = Path("/root/apps/backtest-lab-gallant/.env")
    if env.exists():
        for line in env.read_text().splitlines():
            if line.strip().startswith("AZC_API_KEY="):
                return line.split("=", 1)[1].strip()
    return None


def _champ_signature(champion: dict) -> str:
    params = champion.get("params", {})
    items = ",".join(f"{k}={params[k]}" for k in sorted(params))
    return f"{champion.get('family')}|{items}|{round(float(champion.get('is_score', 0.0)), 5)}"


def maybe_publish_champion(result: dict, store: Store) -> None:
    """Promote a freshly-validated champion to the gallant showcase, once per
    promotion. Env-gated (EVOLAB_PUBLISH != '0'); never raises into the loop."""
    if os.environ.get("EVOLAB_PUBLISH", "1") == "0":
        return
    if not result.get("new_champion"):
        return
    champion = result.get("champion")
    if not champion:
        return
    sig_path = store.base / "published.json"
    try:
        published = {}
        if sig_path.exists():
            published = _json.loads(sig_path.read_text())
        asset = result["asset"]
        sig = _champ_signature(champion)
        if published.get(asset) == sig:
            return
        genome = Genome(champion["family"], champion.get("params", {}))
        publish_genome(asset, genome, base_url=PUBLISH_URL, api_key=_publish_key())
        published[asset] = sig
        write_json_atomic(sig_path, published)
        print(f"[evolab] promoted champion {asset} -> gallant ({sig})", flush=True)
    except Exception as err:
        print(f"[evolab] champion publish FAILED for {result.get('asset')}: {err!r}", flush=True)

GENS_PER_VISIT = int(os.environ.get("EVOLAB_GENS_PER_VISIT", "3"))
SLEEP_SECONDS = int(os.environ.get("EVOLAB_SLEEP_SECONDS", "30"))
POP = int(os.environ.get("EVOLAB_POP", "24"))
# Proposer stall threshold for the daemon's short visits. Low by default so a
# stalled asset can draw an LLM proposal within a 3-gen visit (only matters when
# EVOLAB_LLM_API_KEY is set; otherwise the proposer is disabled entirely).
STALL_GENS = int(os.environ.get("EVOLAB_STALL_GENS", "2"))

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
    propose_fn=None,
    stall_gens: int = STALL_GENS,
) -> list[str]:
    """Evolve every asset once. A failing asset is logged and skipped, never
    aborts the cycle. Returns the assets that advanced this cycle. `propose_fn`,
    when set, enables the LLM proposer on stalled assets (Phase 3)."""
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
                propose_fn=propose_fn, stall_gens=stall_gens,
            )
            advanced.append(asset)
            champ = result.get("champion")
            print(f"[evolab] cycle={cycle} {asset} gen={result['generation']} "
                  f"trials={result['trials_cumulative']} bestIS={result['best_is_score']} "
                  f"champion={'YES ' + champ['family'] if champ else 'none'}", flush=True)
            _write_heartbeat(state_dir, cycle, asset)
            maybe_publish_champion(result, store)
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

    # LLM proposer (Phase 3): enabled only when EVOLAB_LLM_API_KEY is set.
    _client = proposer.client_from_env()
    propose_fn = (lambda recent, champ, n: proposer.propose(_client, recent, champ, n)) if _client else None
    proposer_state = f"ENABLED (model={_client.model})" if _client else "disabled (no EVOLAB_LLM_API_KEY)"

    print(f"[evolab] daemon up: assets={assets} gens/visit={GENS_PER_VISIT} "
          f"sleep={SLEEP_SECONDS}s pop={POP} proposer={proposer_state}", flush=True)

    cycle = 0
    while not _stop:
        cycle += 1
        one_cycle(assets, bars_cache, store, cycle=cycle, propose_fn=propose_fn)
        # Sleep in short slices so SIGTERM is honoured promptly.
        slept = 0
        while slept < SLEEP_SECONDS and not _stop:
            time.sleep(min(2, SLEEP_SECONDS - slept))
            slept += 2

    print("[evolab] SIGTERM received — clean shutdown", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(run_daemon())
