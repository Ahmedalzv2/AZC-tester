from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import random
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from evolab.genome import Genome, genome_key, random_genome
from evolab.population import evolve_generation, select


@dataclass
class _Fit:
    genome: Genome
    is_score: float
    is_t: float = 0.0


def test_select_keeps_highest_is_score_as_elites():
    rng = random.Random(1)
    results = [_Fit(random_genome(rng, "ts_momentum"), is_score=s) for s in (0.1, -0.5, 0.3, 0.0)]
    survivors = select(results, elite_k=1, tourn_k=1, rng=rng)
    assert max(results, key=lambda r: r.is_score).genome in survivors


def test_evolve_generation_fills_to_pop_size_with_unique_genomes():
    rng = random.Random(2)
    survivors = [random_genome(rng, "donchian_break") for _ in range(3)]
    nxt = evolve_generation(survivors, pop_size=20, rng=rng, reseed_frac=0.1)
    assert len(nxt) == 20
    keys = {genome_key(g) for g in nxt}
    assert len(keys) == 20  # deduped
