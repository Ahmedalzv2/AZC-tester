from __future__ import annotations

from pathlib import Path
import random
import sys

import pytest

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


# Multiple (noise-tape, genome-draw) seeds so the guarantee isn't single-seed
# luck. The gate is provably sealed from ~gen 5 (alpha falls below the bootstrap
# p-floor 1/2001); gens 1-4 are the only theoretical window, and distinct tapes
# make a fluke champion in that window vanishingly unlikely.
@pytest.mark.parametrize("data_seed,search_seed", [(42, 1), (7, 5), (123, 9)])
def test_noise_yields_zero_champions(tmp_path, data_seed, search_seed):
    bars = _random_walk(1800, seed=data_seed)
    store = Store(tmp_path)
    result = run_search("NOISE", bars, generations=30, pop_size=24, seed=search_seed, store=store)
    assert result["champion"] is None, (
        f"overfit leak (data={data_seed}, search={search_seed}): {result['champion']}"
    )


def test_same_seed_is_deterministic(tmp_path):
    bars = _random_walk(2000, seed=7)
    r1 = run_search("NOISE", bars, generations=8, pop_size=16, seed=3, store=Store(tmp_path / "a"))
    r2 = run_search("NOISE", bars, generations=8, pop_size=16, seed=3, store=Store(tmp_path / "b"))
    assert r1["best_is_score"] == r2["best_is_score"]
    assert r1["trials_cumulative"] == r2["trials_cumulative"]


from evolab import fitness as _fit


def _trending(n: int, drift: float, seed: int) -> list[Bar]:
    """Persistent uptrend with mild noise -> trend families should dominate IS."""
    rng = random.Random(seed)
    px = 100.0
    bars = []
    for i in range(n):
        px *= (1 + drift + rng.gauss(0, 0.002))
        o = px
        c = px * (1 + drift)
        bars.append(Bar(t=i * 3600_000, o=o, h=max(o, c) * 1.001, l=min(o, c) * 0.999, c=c))
    return bars


def test_trending_data_best_genome_is_a_trend_family(tmp_path):
    bars = _trending(2500, drift=0.0015, seed=11)
    store = Store(tmp_path)
    run_search("TREND", bars, generations=15, pop_size=24, seed=2, store=store)
    from evolab import data as _data
    from evolab.store import genome_from_dict
    splits = _data.split(bars)
    state = store.load_state("TREND")
    best = max(
        (_fit.evaluate(genome_from_dict(d), splits, 1.0) for d in state["population"]),
        key=lambda r: r.is_score,
    )
    assert best.genome.family in _fit.TREND_FAMILIES


def test_cli_runs_on_a_real_asset(tmp_path, monkeypatch, capsys):
    import evolab.search as search_mod
    monkeypatch.setattr(search_mod, "STATE_DIR", tmp_path)
    from evolab import data as _data
    avail = _data.available_assets()
    if not avail:
        pytest.skip("no crypto fixtures mounted")
    rc = search_mod.main([avail[0], "--generations", "1", "--pop", "8", "--seed", "1"])
    assert rc == 0
    assert avail[0] in capsys.readouterr().out
