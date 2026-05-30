from __future__ import annotations

from pathlib import Path
import random
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from engine_bracket import Bar
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


def test_noise_yields_zero_champions(tmp_path):
    bars = _random_walk(2500, seed=42)
    store = Store(tmp_path)
    result = run_search("NOISE", bars, generations=30, pop_size=24, seed=1, store=store)
    assert result["champion"] is None, f"overfit leak: {result['champion']}"


def test_same_seed_is_deterministic(tmp_path):
    bars = _random_walk(2000, seed=7)
    r1 = run_search("NOISE", bars, generations=8, pop_size=16, seed=3, store=Store(tmp_path / "a"))
    r2 = run_search("NOISE", bars, generations=8, pop_size=16, seed=3, store=Store(tmp_path / "b"))
    assert r1["best_is_score"] == r2["best_is_score"]
    assert r1["trials_cumulative"] == r2["trials_cumulative"]
