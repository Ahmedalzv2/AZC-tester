"""Lifecycle evaluator — the daily fair-invalidation judge for a paper lane.

Pure and deterministic: given a lane's forward track record, decide continue vs
invalidate against PRE-REGISTERED thresholds. No auto-retune anywhere — a lane
either keeps running or is retired into the rejection registry. Promotion toward
live capital is a separate, stricter gate (forward HAC t >= 2 sustained), not
handled here.
"""
from __future__ import annotations

from dataclasses import dataclass

# Pre-registered invalidation thresholds (one place to tune).
MAXDD_KILL = -0.20    # hard blow-up kill at any sample size (grids die here on trends)
MIN_TRADES = 30       # minimum closed trades before a no-edge verdict is fair
MIN_DAYS = 45         # ...or this many calendar days, whichever comes first


@dataclass
class Track:
    """A lane's forward track record (real/simulated, net of fees)."""
    n_trades: int
    days: int
    net_r: float      # forward net-R per trade (or total, as long as sign is meaningful)
    hac_t: float      # forward Newey-West t-stat (reported; not the kill trigger)
    max_dd: float     # worst peak-to-trough, as a negative fraction (e.g. -0.24)


def evaluate(track: Track) -> dict:
    """Return {action: continue|invalidate, reason, metrics}. Drawdown breach is
    checked first and overrides everything (a blow-up is fatal even if profitable
    on paper)."""
    metrics = {"net_r": track.net_r, "hac_t": track.hac_t,
               "max_dd": track.max_dd, "n": track.n_trades, "days": track.days}

    if track.max_dd <= MAXDD_KILL:
        return {"action": "invalidate",
                "reason": f"drawdown breach (max_dd {track.max_dd:.2%} <= {MAXDD_KILL:.0%})",
                "metrics": metrics}

    matured = track.n_trades >= MIN_TRADES or track.days >= MIN_DAYS
    if matured and track.net_r <= 0:
        return {"action": "invalidate",
                "reason": (f"no forward edge (net_r {track.net_r:+.4f} <= 0 after "
                           f"{track.n_trades} trades / {track.days}d)"),
                "metrics": metrics}

    return {"action": "continue", "reason": "within tolerance", "metrics": metrics}
