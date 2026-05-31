"""Universe abstraction: lets EvoLab's leaderboard score more than one market
family without entangling the crypto-coupled data.py / publish.py.

A Universe owns everything the best-15 publisher needs that differs by market:
which assets exist, how a tape is loaded + split, the fee model, the per-universe
Store (so deflation budgets never bleed across universes), the OOS scorer, and
the gallant payload shape (interval/fee labels). Two instances:

  - CRYPTO  : today's behavior — AZC hourly fixtures -> 4h, 7.5bps taker, state/.
  - PROVEN  : indices + commodities daily fixtures, 2bp taker, state-proven/.
              The playbook's fundable trend universe (HAC t=9, 21/21 eras).

Crypto delegates to the existing modules so its results are byte-identical to
before; proven is self-contained here (no edit to fitness.py/data.py).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from bracket_signals import SIGNALS, simulate_signal
from engine_bracket import Bar, bracket_metrics
from evolab import data, fitness, publish
from evolab.genome import FIXED_PARAMS, Genome
from evolab.search import STATE_DIR
from evolab.store import Store

# Proven-universe fee: ETF / micro-futures realistic cost (~2bp incl commission
# + slippage), vs crypto's 7.5bps taker. The honest figure from the playbook's
# costed reality-check.
PROVEN_FEE: dict[str, Any] = {
    "makerEntry": False, "makerTp": False, "takerRate": 0.0002, "slipBps": 0,
}
PROVEN_FIX = Path(__file__).resolve().parent / "fixtures" / "proven"
PROVEN_STATE = STATE_DIR.parent / "state-proven"


@dataclass
class ScoreResult:
    """The OOS facts the leaderboard ranks on — same shape a FitnessResult
    exposes, so build_leaderboard treats both universes uniformly."""
    genome: Genome
    oos_t: float
    oos_n: int
    oos_mean: float
    oos_p: float


class Universe:
    name: str
    interval: str
    state_dir: Path

    def store(self) -> Store:
        return Store(self.state_dir)

    def alpha_deflated(self) -> float:
        return self.store().alpha_deflated()

    # subclasses implement:
    def assets(self) -> list[str]: ...
    def load_split(self, asset: str) -> tuple[list[Bar], list[Bar]]: ...
    def score(self, genome: Genome, is_bars: list[Bar], oos_bars: list[Bar]) -> ScoreResult: ...
    def build_payload(self, asset: str, genome: Genome) -> tuple[dict, dict]: ...


class CryptoUniverse(Universe):
    name = "crypto"
    interval = "4h"
    state_dir = STATE_DIR

    def assets(self) -> list[str]:
        return data.available_assets()

    def load_split(self, asset: str) -> tuple[list[Bar], list[Bar]]:
        return data.split(data.load_asset(asset))

    def score(self, genome: Genome, is_bars: list[Bar], oos_bars: list[Bar]) -> ScoreResult:
        # Delegate to fitness.evaluate so crypto scoring stays byte-identical.
        # alpha only gates is_champion_candidate, not the OOS stats we read here.
        r = fitness.evaluate(genome, (is_bars, oos_bars), 1.0)
        return ScoreResult(r.genome, r.oos_t, r.oos_n, r.oos_mean, r.oos_p)

    def build_payload(self, asset: str, genome: Genome) -> tuple[dict, dict]:
        return publish.build_run_payload(asset, genome)


class ProvenUniverse(Universe):
    name = "proven"
    interval = "1d"
    state_dir = PROVEN_STATE

    def assets(self) -> list[str]:
        if not PROVEN_FIX.exists():
            return []
        return sorted(p.stem for p in PROVEN_FIX.glob("*.json"))

    def load_asset(self, asset: str) -> list[Bar]:
        raw = json.loads((PROVEN_FIX / f"{asset}.json").read_text())
        # Daily bars used as-is — NO resample (unlike crypto hourly->4h).
        return [Bar(t=r["t"], o=float(r["o"]), h=float(r["h"]),
                    l=float(r["l"]), c=float(r["c"])) for r in raw]

    def load_split(self, asset: str) -> tuple[list[Bar], list[Bar]]:
        return data.split(self.load_asset(asset))

    def _net_rs(self, bars: list[Bar], genome: Genome) -> np.ndarray:
        fn = SIGNALS[genome.family]
        params = {**genome.params, **FIXED_PARAMS.get(genome.family, {}), **PROVEN_FEE}
        return np.asarray([t["netR"] for t in simulate_signal(bars, fn, params)], dtype=float)

    def score(self, genome: Genome, is_bars: list[Bar], oos_bars: list[Bar]) -> ScoreResult:
        oos_rs = self._net_rs(oos_bars, genome)
        oos_n = int(oos_rs.size)
        oos_mean = float(oos_rs.mean()) if oos_n else 0.0
        return ScoreResult(genome, fitness._tstat(oos_rs), oos_n, oos_mean,
                           fitness._pvalue(oos_rs))

    def build_payload(self, asset: str, genome: Genome) -> tuple[dict, dict]:
        bars = self.load_asset(asset)
        is_bars, oos_bars = data.split(bars)
        fn = SIGNALS[genome.family]
        params = {**genome.params, **FIXED_PARAMS.get(genome.family, {}), **PROVEN_FEE}
        trades = simulate_signal(bars, fn, params)
        bm = bracket_metrics(trades)
        risk_pct = float(genome.params.get("riskPct", publish.DEFAULT_RISK_PCT))
        net_rs = np.asarray([t["netR"] for t in trades], dtype=float)
        sharpe = float(net_rs.mean() / (net_rs.std() + 1e-9)) if net_rs.size else 0.0
        sc = self.score(genome, is_bars, oos_bars)
        fee_bps = round(PROVEN_FEE["takerRate"] * 1e4, 2)

        metrics = {
            "trade_count": bm["n"], "win_rate_pct": round(bm["winPct"], 3),
            "total_r": round(bm["totalR"], 4), "net_r_per_trade": round(bm["netR"], 4),
            "max_drawdown_r": round(bm["maxDD"], 4),
            "total_return_pct": round(bm["totalR"] * risk_pct * 100, 3),
            "max_drawdown_pct": round(-bm["maxDD"] * risk_pct * 100, 3),
            "sharpe": round(sharpe, 3), "strategy": f"evolab:{genome.family}",
            "interval": self.interval, "fee_bps": fee_bps, "fee_model": "2bp-taker",
            "execution": "bracket",
        }
        significance = {
            "tstat": round(sc.oos_t, 4), "pvalue": round(sc.oos_p, 6),
            "mean_return": round(sc.oos_mean, 6), "n": sc.oos_n,
            "significant": False, "scope": "oos",
        }
        request = {
            "strategy": f"evolab:{genome.family}", "data_provider": "yahoo_daily",
            "symbol": asset, "interval": self.interval, "years": 0,
            "strategy_params": dict(genome.params),
        }
        response = {
            "metrics": metrics, "significance": significance, "trades": trades,
            "curve": publish.build_equity_curve([t["netR"] for t in trades], risk_pct),
            "source": {"provider": "evolab-proven",
                       "note": "EvoLab proven-universe genome, daily, 2bp taker"},
            "evolab": {"family": genome.family, "params": dict(genome.params),
                       "universe": self.name, "oos": significance},
        }
        return request, response


CRYPTO = CryptoUniverse()
PROVEN = ProvenUniverse()
UNIVERSES: dict[str, Universe] = {CRYPTO.name: CRYPTO, PROVEN.name: PROVEN}


def get(name: str) -> Universe:
    if name not in UNIVERSES:
        raise KeyError(f"unknown universe '{name}'; known: {sorted(UNIVERSES)}")
    return UNIVERSES[name]
