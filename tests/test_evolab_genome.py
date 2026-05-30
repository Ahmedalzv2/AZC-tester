from __future__ import annotations

from pathlib import Path
import random
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from evolab.genome import PARAM_SCHEMAS, Genome, crossover, genome_key, mutate, random_genome


def _in_schema(g: Genome) -> bool:
    schema = PARAM_SCHEMAS[g.family]
    for name, spec in schema.items():
        v = g.params[name]
        if spec.kind == "choice":
            if v not in spec.choices:
                return False
        else:
            if not (spec.low <= v <= spec.high):
                return False
            # must sit on the discrete search grid, not just within bounds
            steps = round((v - spec.low) / spec.step)
            if abs((spec.low + steps * spec.step) - v) > 1e-9:
                return False
    return True


def test_random_genome_is_schema_legal_for_every_family():
    rng = random.Random(1)
    for family in PARAM_SCHEMAS:
        for _ in range(50):
            g = random_genome(rng, family=family)
            assert g.family == family
            assert _in_schema(g), (family, g.params)


def test_repair_orders_ma_cross_fast_below_slow():
    rng = random.Random(2)
    for _ in range(50):
        g = random_genome(rng, family="ma_cross")
        assert g.params["fast"] < g.params["slow"]


def test_genome_key_dedups_identical_configs():
    a = Genome("ts_momentum", {"mom": 20, "atrN": 14, "atrMult": 2.0, "trail": 3})
    b = Genome("ts_momentum", {"atrMult": 2.0, "trail": 3, "mom": 20, "atrN": 14})
    assert genome_key(a) == genome_key(b)


def test_random_genome_without_family_picks_a_known_family():
    rng = random.Random(9)
    for _ in range(20):
        g = random_genome(rng)
        assert g.family in PARAM_SCHEMAS


def test_mutate_stays_in_schema_bounds():
    rng = random.Random(3)
    for _ in range(200):
        parent = random_genome(rng)
        child = mutate(parent, rng)
        assert child.family == parent.family
        assert _in_schema(child)


def test_mutate_returns_new_object_not_mutating_parent():
    rng = random.Random(4)
    parent = random_genome(rng, family="donchian_break")
    before = dict(parent.params)
    mutate(parent, rng)
    assert parent.params == before


def test_crossover_same_family_is_legal_and_mixes():
    rng = random.Random(5)
    a = random_genome(rng, family="bollinger_fade")
    b = random_genome(rng, family="bollinger_fade")
    # Guard against a vacuous pass: the mixing path is only exercised if the
    # parents actually differ somewhere.
    assert a.params != b.params
    child = crossover(a, b, rng)
    assert child.family == "bollinger_fade"
    assert _in_schema(child)
    for name in PARAM_SCHEMAS["bollinger_fade"]:
        assert child.params[name] in (a.params[name], b.params[name])


def test_crossover_different_family_returns_a_clone():
    rng = random.Random(6)
    a = random_genome(rng, family="ma_cross")
    b = random_genome(rng, family="rsi_reversion")
    child = crossover(a, b, rng)
    assert child.family in ("ma_cross", "rsi_reversion")
    assert child.params in (a.params, b.params)
