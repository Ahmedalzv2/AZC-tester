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
