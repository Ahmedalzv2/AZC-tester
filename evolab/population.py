"""Selection and the per-generation step. Selection is on IS score only; the
genetic operators come from genome.py.
"""
from __future__ import annotations

import random
from typing import Any

from evolab.genome import Genome, crossover, genome_key, mutate, random_genome


def select(results: list[Any], elite_k: int, tourn_k: int, rng: random.Random) -> list[Genome]:
    """Elitism (top by IS score) + tournament selection for the remainder."""
    ranked = sorted(results, key=lambda r: r.is_score, reverse=True)
    survivors = [r.genome for r in ranked[:elite_k]]
    pool = ranked[elite_k:]
    while pool and len(survivors) < elite_k + tourn_k:
        contenders = rng.sample(pool, k=min(3, len(pool)))
        winner = max(contenders, key=lambda r: r.is_score)
        survivors.append(winner.genome)
        pool.remove(winner)
    return survivors


def evolve_generation(
    survivors: list[Genome], pop_size: int, rng: random.Random, reseed_frac: float = 0.1
) -> list[Genome]:
    """Fill the next population from survivors via mutate/crossover + reseeds,
    deduped by genome_key. Falls back to fresh randoms if survivors are scarce."""
    next_pop: list[Genome] = []
    seen: set = set()

    def _add(g: Genome) -> None:
        k = genome_key(g)
        if k not in seen:
            seen.add(k)
            next_pop.append(g)

    for g in survivors:
        _add(g)

    n_reseed = max(1, int(pop_size * reseed_frac))
    guard = 0
    while len(next_pop) < pop_size and guard < pop_size * 50:
        guard += 1
        if len(next_pop) >= pop_size - n_reseed or len(survivors) < 2:
            _add(random_genome(rng))
        else:
            a, b = rng.sample(survivors, 2)
            child = crossover(a, b, rng) if a.family == b.family else mutate(rng.choice([a, b]), rng)
            _add(mutate(child, rng))
    # If dedup couldn't reach pop_size, top up with randoms (guaranteed legal).
    while len(next_pop) < pop_size:
        _add(random_genome(rng))
    return next_pop[:pop_size]
