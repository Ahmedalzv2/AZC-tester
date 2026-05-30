# EvoLab — Autonomous Strategy Search (Phase 1: Evolutionary Search Core)

**Date:** 2026-05-30
**Status:** Design — approved pending user spec review
**Author:** Claude Code (with Ahmed)

## Vision (full system, for context)

backtest-lab should run continuously and, per asset, *keep improving* trading
strategies and surface the best **honest** outcomes — the anti-Trader.dev:
where their leaderboard shows sweep-maxima (+64,000% overfit), ours shows only
strategies that survive deflated, out-of-sample, forward-tested scrutiny.

The full system is **hybrid**: cheap deterministic evolutionary search runs
24/7; an LLM is consulted only rarely (when search plateaus) to inject a new
signal family; the deterministic truth layer (`stats.py` HAC-t/bootstrap +
`overfit.py` DSR/PSR + `walkforward.py`) is always the judge. Scope is **crypto
perps** for now (deep local fixture tape: DOGE/SOL/XRP 5y hourly → 4h, plus any
AZC fixtures present).

This is decomposed into four shippable phases:

1. **Evolutionary search core** (this spec) — per-asset population that mutates
   and keeps the OOS-validated best, with cumulative-trial deflation + a
   persistent champion store. Free, runnable by hand. No daemon, no LLM.
2. **Daemon + dashboard** — systemd long-running loop, asset scheduling,
   CPU/budget guards, per-asset champion leaderboard in the UI.
3. **LLM proposer** — stall detection → pluggable proposer (Ollama 3B or Haiku)
   injects a new signal family. Off by default.
4. **Shadow promotion gate** — champions auto-register into the live shadow
   forward-test; promotion to "real" requires the live t-stat to clear.

Phases 2–4 are **out of scope for this spec** and will each get their own
spec → plan cycle. Everything below is Phase 1 only.

## Non-negotiable disciplines (why this isn't a curve-fit machine)

1. **IS-evolve / OOS-validate.** Selection fitness is computed on the
   **in-sample** slice only. The out-of-sample slice is never optimized
   against — it is used solely to validate whether a genome qualifies as a
   champion. This keeps OOS a genuine holdout.
2. **Cumulative-trial deflation.** The Bonferroni-deflated significance bar
   `α_deflated = 0.05 / cumulative_trials` uses a trial counter persisted
   across every run and generation for the daemon's whole life — not per-run.
   The bar gets *stricter the longer you search*, which is the honest
   accounting that stops a forever-running search from eventually mining a
   fluke.
3. **A champion is a hypothesis, never a result.** The true gate is the
   live shadow forward-test (Phase 4). Phase 1 produces champions; it never
   claims one is "real."

## Phase 1 scope

### In scope
- New `evolab/` package (leaves `strategy_hunt.py` intact as the legacy grid).
- Per-asset evolutionary search over the existing `bracket_signals.SIGNALS`
  families, with declarative per-family param schemas.
- IS-only selection; OOS+deflated champion gate; cumulative trial counter.
- Persistent state: population, per-asset champion, global trial counter, audit
  log.
- CLI entry: `python -m evolab.search <ASSET> [--generations N] [--pop N] [--seed S]`.
- TDD test suite incl. the noise-rejection test.

### Out of scope (later phases)
- Daemon / scheduling / systemd (Phase 2).
- Dashboard surface (Phase 2).
- LLM proposer / new-family invention (Phase 3).
- Shadow forward-test registration/promotion (Phase 4).
- New signal families beyond those already in `SIGNALS`.

## Architecture

```
evolab/
  genome.py       # Genome dataclass, PARAM_SCHEMAS, mutate(), crossover(), random_genome()
  fitness.py      # evaluate(genome, splits) -> FitnessResult (IS score + OOS validation + deflation)
  population.py   # select(), evolve_generation()
  store.py        # load/save per-asset state, champion, global trial counter, audit append
  search.py       # CLI: orchestrates generations for one asset
  state/          # runtime artifacts (gitignored): <asset>.json, trials.json
  runs.jsonl      # append-only audit log (gitignored)
```

Reuses unchanged from the existing codebase:
- `bracket_signals.SIGNALS`, `simulate_signal` — entry logic + bracket sim.
- `engine_bracket.Bar`, `resample_positional` — bar loading/resampling.
- `stats.newey_west_tstat`, `bootstrap_pvalue`, `_default_lags` — HAC-t + p.
- The `TAKER` fee dict and `_load`/`_sig` logic (lifted into `fitness.py`).

### Data flow (one generation, one asset)

1. `store.load_state(asset)` → population (or seed a random one) + asset's
   generation count.
2. For each genome not yet evaluated this generation:
   `fitness.evaluate(genome, splits)` runs `simulate_signal` on IS and OOS bars,
   computes IS score (selection) and OOS stats (validation), increments the
   **global trial counter**, and flags `is_champion_candidate` against the
   current `α_deflated`.
3. `population.select(...)` keeps elites + tournament winners by **IS score**.
4. `population.evolve_generation(...)` fills the next population via
   `mutate`/`crossover` of survivors + a few `random_genome` re-seeds.
5. Update the asset champion if any candidate beats the stored one *and* clears
   the deflated OOS bar.
6. `store.save_state` + `store.append_run` (audit).

## Component detail

### genome.py

```python
@dataclass(frozen=True)
class Genome:
    family: str            # key into bracket_signals.SIGNALS
    params: dict           # family-specific params (no fee keys)
```

- `PARAM_SCHEMAS: dict[str, dict[str, ParamSpec]]` — for each family, each
  tunable param's `(type, low, high, step|choices)`. Example for
  `donchian_break`: `don ∈ int[10..80] step 5`, `atrN ∈ int[7..28] step 7`,
  `atrMult ∈ float[1.5..4.0] step 0.5`, `trail ∈ int[2..5] step 1`,
  `erMin ∈ {0.0, 0.3}`, `regimeN ∈ int[10..40] step 10`.
- `mutate(genome, rng)` — perturb 1–2 params by ±1 step within bounds; returns
  a new Genome. Never produces out-of-bounds values.
- `crossover(a, b, rng)` — same-family only; child takes each param from a or b
  at random. Different families → return a clone of the fitter parent (no-op
  crossover; family change happens via re-seed / Phase 3 LLM).
- `random_genome(rng, family=None)` — sample a legal genome from the schema.
- Genome equality/hash on `(family, sorted params)` for dedup.

### fitness.py

```python
@dataclass
class FitnessResult:
    genome: Genome
    is_n: int; is_score: float          # selection signal (IS mean netR)
    is_t: float
    oos_n: int; oos_mean: float; oos_t: float; oos_p: float
    is_champion_candidate: bool          # passed deflated OOS gate
```

- `evaluate(genome, splits, alpha_deflated)` mirrors today's `_eval_config` but
  **per single asset's splits** (one (is_bars, oos_bars) pair, not pooled).
- Selection score = `is_score` (IS mean netR). Tie-break by `is_t`.
- Champion gate (unchanged thresholds from `strategy_hunt`):
  `oos_n >= 40 and oos_mean > 0 and is_score > 0 and oos_t >= 2.0
   and oos_p < alpha_deflated`.
- **Determinism requirement:** `evaluate` must make `bootstrap_pvalue`
  reproducible — pass a seed if the signature allows, otherwise seed the global
  RNG before the call. Without this the determinism test below is flaky. The
  plan must verify `bootstrap_pvalue`'s signature first and pick the right
  mechanism.

### store.py

- `trials.json`: `{"cumulative": int}`. `bump_trials(n)` adds and persists;
  `alpha_deflated()` returns `0.05 / max(1, cumulative)`.
- `<asset>.json`: `{"asset", "generation", "population": [genome...],
   "champion": {genome, fitness, trials_at_promotion, ts} | null}`.
- `append_run(record)` → one JSON line in `runs.jsonl` per generation:
  `{ts, asset, generation, pop_size, trials_cumulative, alpha_deflated,
    best_is_score, champion_oos_t | null, new_champion: bool}`.
- All paths under `evolab/state/` and `evolab/runs.jsonl`, both gitignored.
- `ts` is passed in (callers stamp it); the module does not call the clock,
  so runs are reproducible/testable.

### population.py

- `select(results, elite_k, tourn_k, rng)` — keep top `elite_k` by IS score,
  then tournament-select the rest. Returns survivor genomes.
- `evolve_generation(survivors, pop_size, rng, reseed_frac=0.1)` — fill to
  `pop_size` via mutate/crossover of survivors plus `reseed_frac` random
  genomes; dedup by genome hash.

### search.py (CLI)

- `python -m evolab.search SOL --generations 20 --pop 40 --seed 7`
- Loads the asset's fixture (resolve `<ASSET>` → fixture filename + resample
  period via a `MARKETS`-style map), builds the IS/OOS split once, then loops
  generations: evaluate → select → evolve → update champion → persist → print a
  one-line generation summary.
- Deterministic given `--seed` (single seeded `random.Random`; no global RNG).
- Parallel evaluation across the 2 cores via `ProcessPoolExecutor` reusing the
  existing worker pattern; falls back to in-process (sandbox-safe).

## Error handling

- Unknown asset / missing fixture → clear `SystemExit` with the list of
  available assets (mirror `azc_fixture`'s available-list message).
- Corrupt/missing state file → start fresh population, log a warning, do not
  crash (the trial counter, if present, is preserved).
- A genome that errors during `simulate_signal` → scored as dead (IS score
  `-inf`, not a candidate); logged; never aborts the generation.
- Empty OOS (too few bars) → genome cannot be a champion; handled by the
  `oos_n >= 40` gate.

## Testing (TDD)

`tests/test_evolab_genome.py`
- `mutate` output is always within schema bounds (property test over many seeds).
- `crossover` of two same-family genomes yields a legal same-family genome.
- `crossover` of different families returns the fitter parent unchanged.
- `random_genome` is always schema-legal.
- Genome hash/equality dedups identical configs.

`tests/test_evolab_fitness.py`
- A planted strong signal in synthetic IS+OOS bars passes the champion gate.
- A genome with `oos_n < 40` is never a candidate.
- `alpha_deflated` shrinks as the trial counter grows (1000 trials ⇒ stricter
  bar than 10).

`tests/test_evolab_store.py`
- Trial counter persists and is monotonic across reload.
- Per-asset state round-trips (population + champion) through save/load.
- SOL state and DOGE state are isolated (writing one doesn't touch the other).

`tests/test_evolab_search.py` (the critical anti-overfit tests)
- **Noise rejection:** on a pure random-walk fixture, 30 generations produce
  **zero** champions (with the cumulative deflation active). This is the test
  that proves the search won't manufacture Trader.dev numbers.
- **Signal recovery:** on a fixture with an embedded exploitable pattern, the
  search promotes a champion whose family matches the planted edge.
- **Determinism:** same `--seed` ⇒ identical final champion + trial count.
- **Per-asset:** running SOL then DOGE yields independent champions and a
  shared (summed) global trial counter.

## Shared-tree safety

backtest-lab is a Hermes/Claude shared working tree with a soft-lock
(`.agent-coordination.md`); the active lock is on the chart layer, untouched
here. All Phase 1 code is **new files** under `evolab/` plus single-line
additions to `.gitignore`. Commits are path-scoped to the files each task
touches — never `git add -A` — so no uncommitted Hermes work is bundled.

## Open questions

None blocking. Asset→fixture resolution reuses the existing `MARKETS` mapping
pattern; if AZC ships more fixtures the map extends trivially. Daemon cadence,
dashboard layout, LLM backend, and shadow-promotion thresholds are deferred to
their own phase specs.
