from __future__ import annotations

import json
from pathlib import Path
import random
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from engine_bracket import Bar
from evolab.daemon import one_cycle
from evolab.store import Store


def _bars(n: int, seed: int) -> list[Bar]:
    rng = random.Random(seed)
    px = 100.0
    out = []
    for i in range(n):
        px *= (1 + rng.gauss(0, 0.01))
        c = px * (1 + rng.gauss(0, 0.003))
        out.append(Bar(t=i * 3600_000, o=px, h=max(px, c) * 1.001, l=min(px, c) * 0.999, c=c))
    return out


def test_one_cycle_advances_state_and_writes_heartbeat(tmp_path):
    store = Store(tmp_path)
    cache = {"TST": _bars(1200, seed=1)}  # prepopulated -> no fixture/load needed
    advanced = one_cycle(["TST"], cache, store, cycle=1, gens=2, pop=12)
    assert advanced == ["TST"]
    state = store.load_state("TST")
    assert state["generation"] == 2
    hb = json.loads((tmp_path / "daemon.json").read_text())
    assert hb["cycle"] == 1 and hb["last_asset"] == "TST"


def test_bad_asset_is_skipped_not_fatal(tmp_path):
    store = Store(tmp_path)
    cache = {"TST": _bars(1200, seed=2)}  # NOPE not in cache and not a real fixture
    advanced = one_cycle(["NOPE", "TST"], cache, store, cycle=1, gens=1, pop=10)
    assert advanced == ["TST"]  # NOPE raised in load_asset, was skipped


def test_cycles_accumulate_generations(tmp_path):
    store = Store(tmp_path)
    cache = {"TST": _bars(1200, seed=3)}
    one_cycle(["TST"], cache, store, cycle=1, gens=2, pop=12)
    one_cycle(["TST"], cache, store, cycle=2, gens=2, pop=12)
    assert store.load_state("TST")["generation"] == 4
    assert store.cumulative_trials() == 48  # 12 pop * 2 gens * 2 cycles
