# EvoLab Phase 1 — Evolutionary Search Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A per-asset evolutionary strategy search that mutates/crosses the existing signal families, selects on in-sample, validates champions out-of-sample under a cumulative-trial-deflated significance bar, and persists champions — runnable by hand, no daemon/LLM.

**Architecture:** New `evolab/` package beside `strategy_hunt.py`. A `Genome` (signal family + params) is mutated/crossed within declarative per-family `PARAM_SCHEMAS`. `fitness.evaluate` runs the existing fee-accurate `simulate_signal` on one asset's IS/OOS split and gates champions with `stats.py`. `store.Store` persists population, per-asset champion, and a global cumulative trial counter that tightens the Bonferroni bar over the search's lifetime.

**Tech Stack:** Python, numpy, pandas, pytest. Reuses `bracket_signals`, `engine_bracket`, `stats`.

**Constraints:** Shared Hermes/Claude tree — all new files under `evolab/`; commits path-scoped (never `git add -A`); chart-layer soft-lock untouched.

---

## File Structure

- **Create** `evolab/__init__.py` — package marker.
- **Create** `evolab/data.py` — asset→fixture map, `load_asset`, `split`, `TAKER`.
- **Create** `evolab/genome.py` — `Genome`, `ParamSpec`, `PARAM_SCHEMAS`, `FIXED_PARAMS`, `random_genome`, `mutate`, `crossover`, `_repair`, `genome_key`.
- **Create** `evolab/fitness.py` — `FitnessResult`, `evaluate`, `TREND_FAMILIES`.
- **Create** `evolab/store.py` — `Store` (trial counter, alpha, per-asset state, audit).
- **Create** `evolab/population.py` — `select`, `evolve_generation`.
- **Create** `evolab/search.py` — `resolve_bars`, `run_search`, `main` CLI.
- **Create** `tests/test_evolab_genome.py`, `tests/test_evolab_fitness.py`, `tests/test_evolab_store.py`, `tests/test_evolab_search.py`.
- **Modify** `.gitignore` — ignore `evolab/state/` and `evolab/runs.jsonl`.

---

### Task 1: Package scaffold + data layer

**Files:**
- Create: `evolab/__init__.py`
- Create: `evolab/data.py`
- Modify: `.gitignore`
- Test: `tests/test_evolab_data.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_evolab_data.py`:

```python
from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from engine_bracket import Bar
from evolab import data


def test_split_respects_oos_fraction():
    bars = [Bar(t=i, o=1.0, h=1.0, l=1.0, c=1.0) for i in range(100)]
    is_bars, oos_bars = data.split(bars, oos_fraction=0.30)
    assert len(is_bars) == 70
    assert len(oos_bars) == 30
    assert is_bars[-1].t == 69
    assert oos_bars[0].t == 70


def test_available_assets_is_a_dict():
    assert isinstance(data.MARKETS, dict)
    assert "SOL" in data.MARKETS
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_evolab_data.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'evolab'`.

- [ ] **Step 3: Create the package + data layer**

Create `evolab/__init__.py` (empty file):

```python
```

Create `evolab/data.py`:

```python
"""Asset → fixture resolution and IS/OOS splitting for EvoLab.

Crypto-perp scope: the deep 5y hourly AZC fixtures, resampled to 4h. Lifts the
loader from strategy_hunt so the search uses the exact same tape.
"""
from __future__ import annotations

import json
from pathlib import Path

from engine_bracket import Bar, resample_positional

FIX = Path("/root/apps/ict-autopilot/tests/fixtures")

# asset -> (fixture filename, resample period in source bars). 5y hourly -> 4h.
MARKETS: dict[str, tuple[str, int]] = {
    "DOGE": ("DOGE-1825d-Min60.json", 4),
    "SOL": ("SOL-1825d-Min60.json", 4),
    "XRP": ("XRP-1825d-Min60.json", 4),
}

# All-taker fees: the honest, fundable assumption (see playbook).
TAKER = {"makerEntry": False, "makerTp": False, "takerRate": 0.00075, "slipBps": 0}

OOS_FRACTION = 0.30


def available_assets() -> list[str]:
    return [a for a, (f, _) in MARKETS.items() if (FIX / f).exists()]


def load_asset(asset: str) -> list[Bar]:
    if asset not in MARKETS:
        raise KeyError(asset)
    name, per = MARKETS[asset]
    raw = json.loads((FIX / name).read_text())
    base = [
        Bar(
            t=(r["t"] if isinstance(r, dict) else r[0]),
            o=float(r["o"] if isinstance(r, dict) else r[1]),
            h=float(r["h"] if isinstance(r, dict) else r[2]),
            l=float(r["l"] if isinstance(r, dict) else r[3]),
            c=float(r["c"] if isinstance(r, dict) else r[4]),
        )
        for r in raw
    ]
    return resample_positional(base, per)


def split(bars: list[Bar], oos_fraction: float = OOS_FRACTION) -> tuple[list[Bar], list[Bar]]:
    k = int(len(bars) * (1 - oos_fraction))
    return bars[:k], bars[k:]
```

- [ ] **Step 4: Update .gitignore (append only — do not reorder existing lines)**

Append to `.gitignore`:

```
evolab/state/
evolab/runs.jsonl
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python -m pytest tests/test_evolab_data.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add evolab/__init__.py evolab/data.py tests/test_evolab_data.py .gitignore
git commit -m "feat(evolab): package scaffold + asset/data layer"
```

---

### Task 2: Genome + schemas + random_genome + repair

**Files:**
- Create: `evolab/genome.py`
- Test: `tests/test_evolab_genome.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_evolab_genome.py`:

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_evolab_genome.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'evolab.genome'`.

- [ ] **Step 3: Implement genome.py (schemas + random + repair)**

Create `evolab/genome.py`:

```python
"""Strategy genomes: a signal family + its tunable params, with declarative
per-family schemas so mutation/crossover only ever produce legal configs.

Fee params and family-fixed params (e.g. trail-exit families pin rr=99) are NOT
part of the genome — fitness.evaluate injects them. The genome carries only the
knobs the search is allowed to turn.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ParamSpec:
    kind: str  # "int" | "float" | "choice"
    low: float = 0.0
    high: float = 0.0
    step: float = 1.0
    choices: tuple = ()


@dataclass
class Genome:
    family: str
    params: dict[str, Any] = field(default_factory=dict)


# Shared exit/risk knobs reused by several families.
_ATR = {
    "atrN": ParamSpec("int", 7, 28, 7),
    "atrMult": ParamSpec("float", 1.5, 4.0, 0.5),
}
_TRAIL = {"trail": ParamSpec("int", 2, 5, 1)}
_RR = {"rr": ParamSpec("float", 1.0, 2.0, 0.5)}

PARAM_SCHEMAS: dict[str, dict[str, ParamSpec]] = {
    "donchian_break": {
        "don": ParamSpec("int", 10, 80, 5), **_ATR, **_TRAIL,
        "erMin": ParamSpec("choice", choices=(0.0, 0.3)),
        "regimeN": ParamSpec("int", 10, 40, 10),
    },
    "donchian_fade": {"don": ParamSpec("int", 10, 80, 5), **_ATR, **_RR},
    "ts_momentum": {"mom": ParamSpec("int", 10, 60, 10), **_ATR, **_TRAIL},
    "ma_cross": {
        "fast": ParamSpec("int", 5, 50, 5),
        "slow": ParamSpec("int", 50, 200, 25), **_ATR, **_TRAIL,
    },
    "rsi_reversion": {
        "rsi_n": ParamSpec("int", 7, 28, 7),
        "lower": ParamSpec("int", 15, 35, 5),
        "upper": ParamSpec("int", 65, 85, 5), **_ATR, **_RR,
    },
    "bollinger_break": {
        "bb_n": ParamSpec("int", 10, 40, 10),
        "bb_k": ParamSpec("float", 1.5, 3.0, 0.5), **_ATR, **_TRAIL,
    },
    "bollinger_fade": {
        "bb_n": ParamSpec("int", 10, 40, 10),
        "bb_k": ParamSpec("float", 1.5, 3.0, 0.5), **_ATR, **_RR,
    },
}

# Params fitness injects but the search never tunes (trail-exit families pin rr).
FIXED_PARAMS: dict[str, dict[str, Any]] = {
    "donchian_break": {"rr": 99},
    "ts_momentum": {"rr": 99},
    "ma_cross": {"rr": 99},
    "bollinger_break": {"rr": 99},
}


def _sample(spec: ParamSpec, rng: random.Random) -> Any:
    if spec.kind == "choice":
        return rng.choice(spec.choices)
    n_steps = int(round((spec.high - spec.low) / spec.step))
    raw = spec.low + rng.randint(0, n_steps) * spec.step
    return int(round(raw)) if spec.kind == "int" else round(raw, 4)


def _clamp(spec: ParamSpec, value: Any) -> Any:
    if spec.kind == "choice":
        return value if value in spec.choices else spec.choices[0]
    value = max(spec.low, min(spec.high, value))
    return int(round(value)) if spec.kind == "int" else round(value, 4)


def _repair(family: str, params: dict[str, Any]) -> dict[str, Any]:
    """Enforce cross-param constraints after sampling/mutation."""
    if family == "ma_cross" and params["fast"] >= params["slow"]:
        params["slow"] = min(200, params["fast"] + 25)
        if params["fast"] >= params["slow"]:
            params["fast"] = max(5, params["slow"] - 25)
    if family == "rsi_reversion" and params["lower"] >= params["upper"]:
        params["lower"], params["upper"] = 30, 70
    return params


def random_genome(rng: random.Random, family: str | None = None) -> Genome:
    family = family or rng.choice(list(PARAM_SCHEMAS))
    params = {name: _sample(spec, rng) for name, spec in PARAM_SCHEMAS[family].items()}
    return Genome(family, _repair(family, params))


def genome_key(g: Genome) -> tuple:
    return (g.family, tuple(sorted(g.params.items())))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_evolab_genome.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add evolab/genome.py tests/test_evolab_genome.py
git commit -m "feat(evolab): genome, param schemas, random_genome + repair"
```

---

### Task 3: Mutation + crossover

**Files:**
- Modify: `evolab/genome.py`
- Modify: `tests/test_evolab_genome.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_evolab_genome.py`:

```python
from evolab.genome import crossover, mutate


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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_evolab_genome.py -k "mutate or crossover" -v`
Expected: FAIL — `ImportError: cannot import name 'crossover'`.

- [ ] **Step 3: Implement mutate + crossover**

Add to `evolab/genome.py`:

```python
def mutate(genome: Genome, rng: random.Random, n_params: int = 1) -> Genome:
    """Perturb 1..n params by +/-1 step (or re-pick a choice), staying legal."""
    schema = PARAM_SCHEMAS[genome.family]
    params = dict(genome.params)
    targets = rng.sample(list(schema), k=min(n_params, len(schema)))
    for name in targets:
        spec = schema[name]
        if spec.kind == "choice":
            params[name] = rng.choice(spec.choices)
        else:
            delta = rng.choice([-1, 1]) * spec.step
            params[name] = _clamp(spec, params[name] + delta)
    return Genome(genome.family, _repair(genome.family, params))


def crossover(a: Genome, b: Genome, rng: random.Random) -> Genome:
    """Same-family uniform crossover. Different families: clone one parent."""
    if a.family != b.family:
        chosen = rng.choice([a, b])
        return Genome(chosen.family, dict(chosen.params))
    params = {name: rng.choice([a.params[name], b.params[name]]) for name in a.params}
    return Genome(a.family, _repair(a.family, params))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_evolab_genome.py -v`
Expected: PASS (all genome tests).

- [ ] **Step 5: Commit**

```bash
git add evolab/genome.py tests/test_evolab_genome.py
git commit -m "feat(evolab): mutation + crossover operators"
```

---

### Task 4: Fitness — per-asset IS-evolve / OOS-validate / deflated gate

**Files:**
- Create: `evolab/fitness.py`
- Test: `tests/test_evolab_fitness.py`

- [ ] **Step 1: Confirm the bootstrap signature (read, no change)**

Run: `python -c "import inspect, stats; print(inspect.signature(stats.bootstrap_pvalue))"`
Expected: `(returns, iterations=2000, seed=0)` — confirms `evaluate` can pass `seed=` for deterministic p-values.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_evolab_fitness.py`:

```python
from __future__ import annotations

from pathlib import Path
import sys

import numpy as np

sys.path.append(str(Path(__file__).resolve().parents[1]))

from engine_bracket import Bar
from evolab import fitness
from evolab.genome import Genome


def _trending_bars(n: int, drift: float) -> list[Bar]:
    bars = []
    px = 100.0
    for i in range(n):
        px *= (1 + drift)
        bars.append(Bar(t=i * 3600_000, o=px, h=px * 1.002, l=px * 0.998, c=px))
    return bars


def test_oos_too_few_trades_is_never_candidate():
    g = Genome("donchian_break", {"don": 55, "atrN": 14, "atrMult": 3.0,
                                  "trail": 3, "erMin": 0.0, "regimeN": 20})
    # 80 bars total -> tiny OOS, far below the 40-trade floor.
    is_bars, oos_bars = _trending_bars(60, 0.001), _trending_bars(20, 0.001)
    res = fitness.evaluate(g, (is_bars, oos_bars), alpha_deflated=0.05)
    assert res.is_champion_candidate is False


def test_strong_signal_passes_champion_gate_directly():
    # Construct an unambiguously significant net-R stream; verify the gate logic
    # (decoupled from the simulator) promotes it.
    strong = np.full(120, 0.25)  # +0.25R every trade, 120 trades
    assert fitness._passes_gate(
        is_score=0.25, oos_n=strong.size, oos_mean=0.25,
        oos_t=fitness._tstat(strong), oos_p=fitness._pvalue(strong),
        alpha_deflated=0.05,
    ) is True


def test_deflation_tightens_with_trials():
    # Same borderline series: passes at a loose alpha, fails at a strict one.
    series = np.concatenate([np.full(50, 0.05), np.full(50, -0.01)])
    p = fitness._pvalue(series)
    t = fitness._tstat(series)
    loose = fitness._passes_gate(0.02, series.size, float(series.mean()), t, p, alpha_deflated=0.05)
    strict = fitness._passes_gate(0.02, series.size, float(series.mean()), t, p, alpha_deflated=1e-6)
    assert loose != strict or (loose is False and strict is False)
    assert strict is False
```

- [ ] **Step 3: Run them to verify they fail**

Run: `python -m pytest tests/test_evolab_fitness.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'evolab.fitness'`.

- [ ] **Step 4: Implement fitness.py**

Create `evolab/fitness.py`:

```python
"""Fitness: evolve on in-sample, validate champions out-of-sample.

Selection score is the IS mean net-R only — the OOS slice is never optimized
against, it just decides whether a genome qualifies as a champion under a
Bonferroni bar that the caller deflates by the cumulative lifetime trial count.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from bracket_signals import SIGNALS, simulate_signal
from engine_bracket import Bar
from evolab.data import TAKER
from evolab.genome import FIXED_PARAMS, Genome
from stats import _default_lags, bootstrap_pvalue, newey_west_tstat

TREND_FAMILIES = {"donchian_break", "ts_momentum", "ma_cross", "bollinger_break"}
MIN_OOS_TRADES = 40
P_SEED = 0  # fixed -> deterministic bootstrap p-values


@dataclass
class FitnessResult:
    genome: Genome
    is_n: int
    is_score: float
    is_t: float
    oos_n: int
    oos_mean: float
    oos_t: float
    oos_p: float
    is_champion_candidate: bool


def _tstat(arr: np.ndarray) -> float:
    a = np.asarray(arr, dtype=float)
    return float(newey_west_tstat(a, lags=_default_lags(a.size))) if a.size >= 2 else 0.0


def _pvalue(arr: np.ndarray) -> float:
    a = np.asarray(arr, dtype=float)
    return float(bootstrap_pvalue(a, seed=P_SEED)) if a.size >= 2 else 1.0


def _passes_gate(is_score, oos_n, oos_mean, oos_t, oos_p, alpha_deflated) -> bool:
    return bool(
        oos_n >= MIN_OOS_TRADES and oos_mean > 0 and is_score > 0
        and oos_t >= 2.0 and oos_p < alpha_deflated
    )


def _net_rs(bars: list[Bar], genome: Genome) -> list[float]:
    fn = SIGNALS[genome.family]
    params = {**genome.params, **FIXED_PARAMS.get(genome.family, {}), **TAKER}
    return [t["netR"] for t in simulate_signal(bars, fn, params)]


def evaluate(genome: Genome, splits: tuple[list[Bar], list[Bar]], alpha_deflated: float) -> FitnessResult:
    is_bars, oos_bars = splits
    try:
        is_rs = np.asarray(_net_rs(is_bars, genome), dtype=float)
        oos_rs = np.asarray(_net_rs(oos_bars, genome), dtype=float)
    except Exception:
        # A broken genome scores as dead, never aborts the generation.
        return FitnessResult(genome, 0, float("-inf"), 0.0, 0, 0.0, 0.0, 1.0, False)

    is_score = float(is_rs.mean()) if is_rs.size else float("-inf")
    oos_mean = float(oos_rs.mean()) if oos_rs.size else 0.0
    oos_t, oos_p = _tstat(oos_rs), _pvalue(oos_rs)
    candidate = _passes_gate(is_score, oos_rs.size, oos_mean, oos_t, oos_p, alpha_deflated)
    return FitnessResult(
        genome=genome, is_n=int(is_rs.size), is_score=is_score, is_t=_tstat(is_rs),
        oos_n=int(oos_rs.size), oos_mean=oos_mean, oos_t=oos_t, oos_p=oos_p,
        is_champion_candidate=candidate,
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_evolab_fitness.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add evolab/fitness.py tests/test_evolab_fitness.py
git commit -m "feat(evolab): per-asset fitness, IS-evolve/OOS-validate gate"
```

---

### Task 5: Store — cumulative trial counter + deflated alpha

**Files:**
- Create: `evolab/store.py`
- Test: `tests/test_evolab_store.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_evolab_store.py`:

```python
from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from evolab.store import Store


def test_trial_counter_is_monotonic_across_reload(tmp_path):
    s = Store(tmp_path)
    s.bump_trials(10)
    s.bump_trials(5)
    assert s.cumulative_trials() == 15
    # Fresh instance, same dir -> persisted.
    assert Store(tmp_path).cumulative_trials() == 15


def test_alpha_deflated_tightens_as_trials_grow(tmp_path):
    s = Store(tmp_path)
    s.bump_trials(10)
    loose = s.alpha_deflated()
    s.bump_trials(990)
    strict = s.alpha_deflated()
    assert strict < loose
    assert abs(loose - 0.05 / 10) < 1e-12
    assert abs(strict - 0.05 / 1000) < 1e-12
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_evolab_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'evolab.store'`.

- [ ] **Step 3: Implement the trial-counter half of store.py**

Create `evolab/store.py`:

```python
"""Persistence: global cumulative trial counter (deflation), per-asset state
(population + champion), and an append-only audit log.

The trial counter is the honest-accounting heart: alpha_deflated = 0.05 /
cumulative_trials, so the significance bar tightens for the whole life of the
search, not per run.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evolab.genome import Genome


class Store:
    def __init__(self, base_dir: Path):
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)
        self._trials_path = self.base / "trials.json"
        self._runs_path = self.base / "runs.jsonl"

    # ── cumulative trial counter ──────────────────────────────────────────
    def cumulative_trials(self) -> int:
        if not self._trials_path.exists():
            return 0
        try:
            return int(json.loads(self._trials_path.read_text()).get("cumulative", 0))
        except (json.JSONDecodeError, ValueError):
            return 0

    def bump_trials(self, n: int) -> int:
        total = self.cumulative_trials() + int(n)
        self._trials_path.write_text(json.dumps({"cumulative": total}))
        return total

    def alpha_deflated(self) -> float:
        return 0.05 / max(1, self.cumulative_trials())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_evolab_store.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add evolab/store.py tests/test_evolab_store.py
git commit -m "feat(evolab): store trial counter + deflated alpha"
```

---

### Task 6: Store — per-asset state round-trip, isolation, audit log

**Files:**
- Modify: `evolab/store.py`
- Modify: `tests/test_evolab_store.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_evolab_store.py`:

```python
from evolab.genome import Genome


def _state(asset, champ_family):
    g = Genome("ts_momentum", {"mom": 20, "atrN": 14, "atrMult": 2.0, "trail": 3})
    return {
        "asset": asset, "generation": 3,
        "population": [{"family": g.family, "params": g.params}],
        "champion": {"family": champ_family, "params": {"mom": 30}},
    }


def test_per_asset_state_round_trips(tmp_path):
    s = Store(tmp_path)
    s.save_state("SOL", _state("SOL", "ts_momentum"))
    loaded = s.load_state("SOL")
    assert loaded["generation"] == 3
    assert loaded["champion"]["family"] == "ts_momentum"
    assert loaded["population"][0]["family"] == "ts_momentum"


def test_assets_are_isolated(tmp_path):
    s = Store(tmp_path)
    s.save_state("SOL", _state("SOL", "ts_momentum"))
    s.save_state("DOGE", _state("DOGE", "donchian_break"))
    assert s.load_state("SOL")["champion"]["family"] == "ts_momentum"
    assert s.load_state("DOGE")["champion"]["family"] == "donchian_break"


def test_missing_state_returns_empty_default(tmp_path):
    s = Store(tmp_path)
    loaded = s.load_state("XRP")
    assert loaded["population"] == []
    assert loaded["champion"] is None


def test_append_run_writes_one_line_per_call(tmp_path):
    s = Store(tmp_path)
    s.append_run({"asset": "SOL", "generation": 1, "new_champion": False})
    s.append_run({"asset": "SOL", "generation": 2, "new_champion": True})
    lines = (tmp_path / "runs.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["new_champion"] is True
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_evolab_store.py -k "round_trips or isolated or missing_state or append_run" -v`
Expected: FAIL — `AttributeError: 'Store' object has no attribute 'save_state'`.

- [ ] **Step 3: Implement the state + audit half of store.py**

Add to the `Store` class in `evolab/store.py`:

```python
    # ── per-asset state ───────────────────────────────────────────────────
    def _state_path(self, asset: str) -> Path:
        return self.base / f"{asset}.json"

    def load_state(self, asset: str) -> dict[str, Any]:
        path = self._state_path(asset)
        if not path.exists():
            return {"asset": asset, "generation": 0, "population": [], "champion": None}
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return {"asset": asset, "generation": 0, "population": [], "champion": None}

    def save_state(self, asset: str, state: dict[str, Any]) -> None:
        self._state_path(asset).write_text(json.dumps(state))

    # ── audit log ─────────────────────────────────────────────────────────
    def append_run(self, record: dict[str, Any]) -> None:
        with self._runs_path.open("a") as f:
            f.write(json.dumps(record) + "\n")
```

Also add genome (de)serialization helpers at module level (used by search.py):

```python
def genome_to_dict(g: Genome) -> dict[str, Any]:
    return {"family": g.family, "params": g.params}


def genome_from_dict(d: dict[str, Any]) -> Genome:
    return Genome(d["family"], dict(d["params"]))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_evolab_store.py -v`
Expected: PASS (all store tests).

- [ ] **Step 5: Commit**

```bash
git add evolab/store.py tests/test_evolab_store.py
git commit -m "feat(evolab): per-asset state round-trip + audit log"
```

---

### Task 7: Population — selection + generation step

**Files:**
- Create: `evolab/population.py`
- Test: `tests/test_evolab_population.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_evolab_population.py`:

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_evolab_population.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'evolab.population'`.

- [ ] **Step 3: Implement population.py**

Create `evolab/population.py`:

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_evolab_population.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add evolab/population.py tests/test_evolab_population.py
git commit -m "feat(evolab): selection + generation step"
```

---

### Task 8: Search orchestration (run_search core)

**Files:**
- Create: `evolab/search.py`
- Test: `tests/test_evolab_search.py`

- [ ] **Step 1: Write the failing tests (noise rejection + determinism)**

Create `tests/test_evolab_search.py`:

```python
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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_evolab_search.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'evolab.search'`.

- [ ] **Step 3: Implement search.py (core, no CLI yet)**

Create `evolab/search.py`:

```python
"""EvoLab search orchestration: evolve one asset for N generations.

run_search is the pure, testable core (takes bars + a Store). The CLI (added
next) just resolves an asset name to bars and calls it.
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path
from typing import Any

from engine_bracket import Bar
from evolab import data, fitness
from evolab.genome import Genome, genome_key, random_genome
from evolab.population import evolve_generation, select
from evolab.store import Store, genome_from_dict, genome_to_dict

STATE_DIR = Path(__file__).resolve().parent / "state"
ELITE_K = 4
TOURN_K = 6


def _better(a: fitness.FitnessResult, b_champ: dict | None) -> bool:
    if not a.is_champion_candidate:
        return False
    if b_champ is None:
        return True
    return a.is_score > float(b_champ.get("is_score", float("-inf")))


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
    best_is_score = float("-inf")

    for _ in range(generations):
        alpha = store.alpha_deflated()
        results = [fitness.evaluate(g, splits, alpha) for g in population]
        store.bump_trials(len(results))
        # Re-read alpha AFTER bumping so the champion gate reflects the now-larger
        # cumulative count (stricter as the search proceeds).
        alpha_after = store.alpha_deflated()

        for r in results:
            best_is_score = max(best_is_score, r.is_score)
            promoted = fitness.evaluate(r.genome, splits, alpha_after) if alpha_after != alpha else r
            if _better(promoted, champion):
                champion = {
                    **genome_to_dict(promoted.genome),
                    "is_score": promoted.is_score, "oos_t": promoted.oos_t,
                    "oos_p": promoted.oos_p, "oos_n": promoted.oos_n,
                    "trials_at_promotion": store.cumulative_trials(), "ts": ts,
                }

        survivors = select(results, ELITE_K, TOURN_K, rng)
        population = evolve_generation(survivors, pop_size, rng)
        generation += 1
        store.append_run({
            "ts": ts, "asset": asset, "generation": generation,
            "pop_size": pop_size, "trials_cumulative": store.cumulative_trials(),
            "alpha_deflated": store.alpha_deflated(),
            "best_is_score": round(best_is_score, 5),
            "champion_oos_t": (champion or {}).get("oos_t"),
            "new_champion": bool(champion and champion.get("trials_at_promotion") == store.cumulative_trials()),
        })

    store.save_state(asset, {
        "asset": asset, "generation": generation,
        "population": [genome_to_dict(g) for g in population],
        "champion": champion,
    })
    return {
        "asset": asset, "generation": generation, "champion": champion,
        "best_is_score": round(best_is_score, 5),
        "trials_cumulative": store.cumulative_trials(),
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_evolab_search.py -v`
Expected: PASS (2 passed). The noise test is the critical one — zero champions on a random walk.

> If `test_noise_yields_zero_champions` ever fails, do NOT loosen it. A champion on pure noise is a real defect in the deflation/gate — debug that, because it is exactly the Trader.dev failure mode the system exists to prevent.

- [ ] **Step 5: Commit**

```bash
git add evolab/search.py tests/test_evolab_search.py
git commit -m "feat(evolab): run_search core + noise-rejection/determinism tests"
```

---

### Task 9: Signal-recovery test + CLI entrypoint

**Files:**
- Modify: `evolab/search.py`
- Modify: `tests/test_evolab_search.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_evolab_search.py`:

```python
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
    # Re-evaluate the saved population to find the IS-best family deterministically.
    from evolab import data as _data
    splits = _data.split(bars)
    state = store.load_state("TREND")
    from evolab.store import genome_from_dict
    best = max(
        (fitness.evaluate(genome_from_dict(d), splits, 1.0) for d in state["population"]),
        key=lambda r: r.is_score,
    )
    assert best.genome.family in _fit.TREND_FAMILIES


def test_cli_runs_on_a_real_asset(tmp_path, monkeypatch, capsys):
    import evolab.search as search_mod
    monkeypatch.setattr(search_mod, "STATE_DIR", tmp_path)
    avail = __import__("evolab.data", fromlist=["available_assets"]).available_assets()
    if not avail:
        import pytest
        pytest.skip("no crypto fixtures mounted")
    rc = search_mod.main([avail[0], "--generations", "1", "--pop", "8", "--seed", "1"])
    assert rc == 0
    assert avail[0] in capsys.readouterr().out
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_evolab_search.py -k "trend_family or cli" -v`
Expected: FAIL — `AttributeError: module 'evolab.search' has no attribute 'main'`.

- [ ] **Step 3: Add resolve_bars + main CLI to search.py**

Append to `evolab/search.py`:

```python
def resolve_bars(asset: str) -> list[Bar]:
    if asset not in data.MARKETS:
        raise SystemExit(f"Unknown asset '{asset}'. Available: {', '.join(data.available_assets()) or '(none mounted)'}")
    if asset not in data.available_assets():
        raise SystemExit(f"Asset '{asset}' has no fixture mounted at {data.FIX}")
    return data.load_asset(asset)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="evolab.search", description="Evolve strategies for one crypto-perp asset.")
    ap.add_argument("asset")
    ap.add_argument("--generations", type=int, default=20)
    ap.add_argument("--pop", type=int, default=40)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    bars = resolve_bars(args.asset)
    store = Store(STATE_DIR)
    result = run_search(
        args.asset, bars, generations=args.generations, pop_size=args.pop,
        seed=args.seed, store=store,
    )
    champ = result["champion"]
    print(f"{result['asset']}: gen={result['generation']} "
          f"trials={result['trials_cumulative']} best_IS={result['best_is_score']:+.4f}")
    if champ:
        print(f"  CHAMPION {champ['family']} {champ['params']} "
              f"OOS_t={champ['oos_t']:+.2f} OOS_p={champ['oos_p']:.4f}")
    else:
        print("  no champion survives the deflated OOS bar (honest null result)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_evolab_search.py -v`
Expected: PASS (all search tests; the CLI test skips if no fixtures are mounted).

- [ ] **Step 5: Run the full EvoLab suite + a real smoke run**

Run: `python -m pytest tests/test_evolab_*.py -q`
Expected: all EvoLab tests pass.

Run (smoke, if fixtures mounted): `python -m evolab.search SOL --generations 5 --pop 24 --seed 1`
Expected: a summary line; likely "no champion survives" (which is the correct, honest outcome on real crypto perps per the playbook — a champion would be a notable event to forward-test, not a bug).

- [ ] **Step 6: Commit**

```bash
git add evolab/search.py tests/test_evolab_search.py
git commit -m "feat(evolab): signal-recovery test + CLI entrypoint"
```

---

## Self-Review Notes

- **Spec coverage:** `evolab/` package (T1), genome+schemas+mutate/crossover (T2–T3), per-asset IS-evolve/OOS-validate fitness with the deterministic bootstrap requirement (T4, signature verified in T4 Step 1), cumulative-trial deflation + per-asset state + audit log (T5–T6), evolutionary selection/generation (T7), orchestration with noise-rejection/determinism/signal-recovery tests + CLI (T8–T9). Disciplines #1 (IS-only selection — `select` ranks on `is_score`), #2 (cumulative deflation — `Store.alpha_deflated` over a persisted counter, re-read after bump in `run_search`), #3 (champion = hypothesis — CLI prints "no champion survives" as the expected honest outcome) all implemented. Out-of-scope items (daemon, dashboard, LLM, shadow) correctly absent.
- **Placeholder scan:** no TBD/"handle edge cases"; every code step has full code; broken-genome handling is concrete (`evaluate` try/except → dead score); missing-state/corrupt-file handling is concrete in `Store`.
- **Type consistency:** `Genome(family, params)` constructed identically everywhere; `FitnessResult.is_score`/`is_champion_candidate`/`oos_t`/`oos_p`/`oos_n` names match across T4, T7 (`select` uses `is_score`), T8 (`_better` uses `is_score`/`is_champion_candidate`). `genome_to_dict`/`genome_from_dict` defined in T6, imported in T8. `Store.alpha_deflated`/`bump_trials`/`cumulative_trials`/`load_state`/`save_state`/`append_run` consistent T5/T6/T8. `genome_key` (T2) used in T7 dedup. `select(results, elite_k, tourn_k, rng)` signature matches its call in T8 (`select(results, ELITE_K, TOURN_K, rng)`).
- **Known soft spot:** `test_trending_data_best_genome_is_a_trend_family` asserts the IS-best family is a trend family on a strongly trending series — robust because it checks *family*, not passing the strict significance bar. If it proves flaky across seeds, strengthen the planted drift rather than weakening the assertion.
- **Shared-tree safety:** all new files under `evolab/` + `tests/test_evolab_*.py`; only `.gitignore` is modified (append). Every commit path-scoped.
