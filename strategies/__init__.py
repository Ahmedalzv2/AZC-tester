from __future__ import annotations

from strategies.azc_bracket import MEANREV as AZC_MEANREV
from strategies.azc_bracket import TREND as AZC_TREND
from strategies.base import StrategySpec
from strategies.breakout import SPEC as BREAKOUT
from strategies.custom_python import SPEC as CUSTOM_PYTHON
from strategies.rsi_reversion import SPEC as RSI_REVERSION
from strategies.sma_cross import SPEC as SMA_CROSS
from strategies.trend_trail import SPEC as TREND_TRAIL

STRATEGIES: dict[str, StrategySpec] = {
    spec.name: spec
    for spec in [AZC_TREND, AZC_MEANREV, TREND_TRAIL, SMA_CROSS, RSI_REVERSION, BREAKOUT, CUSTOM_PYTHON]
}


def list_strategies() -> dict[str, dict[str, object]]:
    return {
        name: {
            "label": spec.label,
            "params": spec.params,
            "uses_custom_code": spec.uses_custom_code,
            "execution": getattr(spec, "execution", "position"),
        }
        for name, spec in STRATEGIES.items()
    }


__all__ = ["STRATEGIES", "StrategySpec", "list_strategies"]
