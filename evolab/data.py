"""Asset → fixture resolution and IS/OOS splitting for EvoLab.

Crypto-perp scope: the deep 5y hourly AZC fixtures, resampled to 4h. Mirrors
the loader/tape config from strategy_hunt (which stays intact as the legacy
grid) so EvoLab searches the exact same bars.
"""
from __future__ import annotations

import json
from pathlib import Path

from engine_bracket import Bar, resample_positional

FIX = Path("/root/apps/ict-autopilot/tests/fixtures")


def _discover_markets() -> dict[str, tuple[str, int]]:
    """Auto-map every mounted hourly (Min60) fixture to asset -> (file, 4h).

    The gateway used to be hardcoded to SOL/DOGE/XRP, but ~30 symbols are
    mounted. Discover them all; when a symbol has multiple tapes (e.g. SOL has
    both 1825d and 1095d), keep the DEEPEST (most days) for the most OOS power.
    Stem shape: "<SYM>-<N>d-Min60". Period 4 = hourly -> 4h (AZC cadence).
    """
    best: dict[str, tuple[int, str]] = {}
    if not FIX.exists():
        return {}
    for path in sorted(FIX.glob("*-Min60.json")):
        stem = path.stem  # e.g. SOL-1825d-Min60
        parts = stem.split("-")
        if len(parts) < 3:
            continue
        sym = parts[0].upper()
        days_tok = parts[1]
        try:
            days = int(days_tok.rstrip("dD"))
        except ValueError:
            continue
        if sym not in best or days > best[sym][0]:
            best[sym] = (days, path.name)
    return {sym: (fname, 4) for sym, (days, fname) in sorted(best.items())}


# asset -> (fixture filename, resample period in source bars). hourly -> 4h.
# Auto-discovered from the mounted tape so the gateway covers the full basket.
MARKETS: dict[str, tuple[str, int]] = _discover_markets()

# All-taker fees: the honest, fundable assumption (see playbook).
TAKER: dict[str, bool | float | int] = {
    "makerEntry": False, "makerTp": False, "takerRate": 0.00075, "slipBps": 0,
}

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
