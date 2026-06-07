from __future__ import annotations

from pathlib import Path
import json
import random
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from engine_bracket import Bar
from evolab.genome import random_genome
from evolab.search import run_search
from evolab.store import Store


def _random_walk(n: int, seed: int) -> list[Bar]:
    rng = random.Random(seed)
    px = 100.0
    bars = []
    for i in range(n):
        px *= (1 + rng.gauss(0, 0.01))
        c = px * (1 + rng.gauss(0, 0.003))
        o = px
        bars.append(Bar(t=i * 3600_000, o=o, h=max(o, c) * 1.001, l=min(o, c) * 0.999, c=c))
    return bars


def test_proposer_invoked_on_stall(tmp_path):
    # Noise data never births a champion and IS score plateaus, so a >=2-gen
    # stall is reached well within 12 generations.
    bars = _random_walk(1600, seed=3)
    fixed = random_genome(random.Random(99))
    calls = []

    def propose_fn(recent, champion, n):
        calls.append((recent, n))
        return [fixed]

    run_search("NOISE", bars, generations=12, pop_size=12, seed=1,
               store=Store(tmp_path), propose_fn=propose_fn, stall_gens=2)

    assert calls, "propose_fn never called despite a stall on noise data"
    recent, n = calls[0]
    assert n > 0 and isinstance(recent, list)
    runs = (tmp_path / "runs.jsonl").read_text().splitlines()
    assert any(json.loads(r).get("injected", 0) > 0 for r in runs)


def test_proposer_not_invoked_before_stall(tmp_path):
    bars = _random_walk(1600, seed=3)
    calls = []

    def propose_fn(recent, champion, n):
        calls.append(1)
        return []

    # stall_gens larger than the run length -> stall threshold never reached.
    run_search("NOISE", bars, generations=3, pop_size=12, seed=1,
               store=Store(tmp_path), propose_fn=propose_fn, stall_gens=10)
    assert calls == []


def test_no_proposer_is_backwards_compatible(tmp_path):
    bars = _random_walk(1200, seed=5)
    run_search("NOISE", bars, generations=4, pop_size=10, seed=1, store=Store(tmp_path))
    runs = (tmp_path / "runs.jsonl").read_text().splitlines()
    assert all(json.loads(r).get("injected", 0) == 0 for r in runs)


def test_daemon_one_cycle_threads_propose_fn(tmp_path):
    from evolab.daemon import one_cycle
    bars = _random_walk(1600, seed=3)
    calls = []

    def propose_fn(recent, champion, n):
        calls.append(1)
        return []

    one_cycle(["NOISE"], {"NOISE": bars}, Store(tmp_path), cycle=1, gens=10,
              pop=12, state_dir=tmp_path, propose_fn=propose_fn, stall_gens=2)
    assert calls, "daemon one_cycle did not pass propose_fn through to the search"
