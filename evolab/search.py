"""EvoLab search orchestration: evolve one asset for N generations.

run_search is the pure, testable core (takes bars + a Store). The CLI (added
in Task 9) just resolves an asset name to bars and calls it.
"""
from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from engine_bracket import Bar
from evolab import data, fitness
from evolab.genome import random_genome
from evolab.population import evolve_generation, select
from evolab.store import Store, genome_from_dict, genome_to_dict

STATE_DIR = Path(__file__).resolve().parent / "state"
ELITE_K = 4
TOURN_K = 6


def run_search(
    asset: str,
    bars: list[Bar],
    *,
    generations: int,
    pop_size: int,
    seed: int,
    store: Store,
    ts: int | None = None,
) -> dict[str, Any]:
    rng = random.Random(seed)
    splits = data.split(bars)

    state = store.load_state(asset)
    population = [genome_from_dict(d) for d in state.get("population", [])]
    if not population:
        population = [random_genome(rng) for _ in range(pop_size)]
    champion = state.get("champion")
    generation = int(state.get("generation", 0))
    # Run-local (reset each call), not the lifetime best — the persisted champion
    # is the durable record across resumed runs.
    best_is_score = float("-inf")

    for _ in range(generations):
        alpha = store.alpha_deflated()
        results = [fitness.evaluate(g, splits, alpha) for g in population]
        store.bump_trials(len(results))
        # Re-test the champion gate against the post-bump (stricter) alpha. The
        # gate is a pure function of already-computed stats — no re-backtest.
        alpha_after = store.alpha_deflated()

        dead = 0
        new_champion_this_gen = False
        for r in results:
            if r.is_score == float("-inf"):
                dead += 1
                continue
            best_is_score = max(best_is_score, r.is_score)
            candidate = fitness._passes_gate(
                r.is_score, r.oos_n, r.oos_mean, r.oos_t, r.oos_p, alpha_after
            )
            if candidate and (champion is None or r.is_score > champion["is_score"]):
                champion = {
                    **genome_to_dict(r.genome),
                    "is_score": r.is_score, "oos_t": r.oos_t,
                    "oos_p": r.oos_p, "oos_n": r.oos_n,
                    "trials_at_promotion": store.cumulative_trials(), "ts": ts,
                }
                new_champion_this_gen = True

        survivors = select(results, ELITE_K, TOURN_K, rng)
        population = evolve_generation(survivors, pop_size, rng)
        generation += 1
        store.append_run({
            "ts": ts, "asset": asset, "generation": generation,
            "pop_size": pop_size, "dead": dead,
            "trials_cumulative": store.cumulative_trials(),
            "alpha_deflated": store.alpha_deflated(),
            "best_is_score": round(best_is_score, 5) if best_is_score != float("-inf") else None,
            "champion_oos_t": (champion or {}).get("oos_t"),
            "new_champion": new_champion_this_gen,
        })

    store.save_state(asset, {
        "asset": asset, "generation": generation,
        "population": [genome_to_dict(g) for g in population],
        "champion": champion,
    })
    return {
        "asset": asset, "generation": generation, "champion": champion,
        "best_is_score": round(best_is_score, 5) if best_is_score != float("-inf") else None,
        "trials_cumulative": store.cumulative_trials(),
    }
