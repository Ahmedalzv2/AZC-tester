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
    # Snap to the nearest grid point so post-mutation values can't drift off the
    # discrete search grid (keeps genome_key dedup meaningful).
    steps = round((value - spec.low) / spec.step)
    value = spec.low + steps * spec.step
    return int(round(value)) if spec.kind == "int" else round(value, 4)


def _repair(family: str, params: dict[str, Any]) -> dict[str, Any]:
    """Enforce cross-param constraints. Returns a NEW dict so a caller's parent
    params are never mutated in place (crossover/mutation share param values)."""
    params = dict(params)
    if family == "ma_cross" and params["fast"] >= params["slow"]:
        # Smallest on-grid slow (step 25) strictly greater than fast (max 50).
        params["slow"] = 50 if params["fast"] < 50 else 75
    if family == "rsi_reversion" and params["lower"] >= params["upper"]:
        params["lower"], params["upper"] = 30, 70  # schema-legal centres
    return params


def random_genome(rng: random.Random, family: str | None = None) -> Genome:
    family = family or rng.choice(list(PARAM_SCHEMAS))
    params = {name: _sample(spec, rng) for name, spec in PARAM_SCHEMAS[family].items()}
    return Genome(family, _repair(family, params))


def genome_key(g: Genome) -> tuple:
    return (g.family, tuple(sorted(g.params.items())))
