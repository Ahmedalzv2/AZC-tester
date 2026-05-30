from __future__ import annotations

from pathlib import Path
import random
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from evolab.genome import PARAM_SCHEMAS, Genome, genome_key, random_genome


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
