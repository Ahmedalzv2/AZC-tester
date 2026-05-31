from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from evolab import best_candidates as bc
from evolab.genome import Genome
from evolab.store import Store, genome_to_dict


def _seed_population(base: Path, asset: str, genomes: list[Genome]) -> None:
    s = Store(base)
    state = {"asset": asset, "generation": 1,
             "population": [genome_to_dict(g) for g in genomes], "champion": None}
    s.save_state(asset, state)


def test_build_leaderboard_ranks_by_oos_t_and_caps_top_n(tmp_path, monkeypatch):
    # Two assets, a few genomes each. Stub fitness.evaluate so the ranking is
    # deterministic and independent of real price data: oos_t keyed off a param.
    g = lambda fam, t: Genome(fam, {"don": t, "atrN": 14, "atrMult": 3.0,
                                    "trail": 3, "erMin": 0.0, "regimeN": 20})
    _seed_population(tmp_path, "SOL", [g("donchian_break", 10), g("donchian_break", 30)])
    _seed_population(tmp_path, "XRP", [g("donchian_break", 20), g("donchian_break", 5)])

    class _R:  # minimal FitnessResult stand-in
        def __init__(self, genome):
            self.genome = genome
            self.oos_t = float(genome.params["don"])   # don=t-stat for the test
            self.oos_n = 50                            # all above MIN_OOS_TRADES
            self.oos_mean = 0.01
            self.oos_p = 0.1

    monkeypatch.setattr(bc, "STATE_DIR", tmp_path)
    monkeypatch.setattr(bc.fitness, "evaluate", lambda genome, splits, alpha: _R(genome))
    monkeypatch.setattr(bc.data, "split", lambda bars: ([], []))
    monkeypatch.setattr(bc.data, "load_asset", lambda asset: [])

    board = bc.build_leaderboard(assets=["SOL", "XRP"], top_n=3)

    assert [c.oos_t for c in board] == [30.0, 20.0, 10.0]   # ranked desc, capped at 3
    assert board[0].asset == "SOL" and board[1].asset == "XRP"


def test_build_leaderboard_drops_thin_oos(tmp_path, monkeypatch):
    g = Genome("donchian_break", {"don": 99, "atrN": 14, "atrMult": 3.0,
                                  "trail": 3, "erMin": 0.0, "regimeN": 20})
    _seed_population(tmp_path, "SOL", [g])

    class _Thin:
        def __init__(self, genome):
            self.genome = genome
            self.oos_t = 99.0
            self.oos_n = bc.fitness.MIN_OOS_TRADES - 1   # below the floor -> dropped
            self.oos_mean = 0.01
            self.oos_p = 0.1

    monkeypatch.setattr(bc, "STATE_DIR", tmp_path)
    monkeypatch.setattr(bc.fitness, "evaluate", lambda genome, splits, alpha: _Thin(genome))
    monkeypatch.setattr(bc.data, "split", lambda bars: ([], []))
    monkeypatch.setattr(bc.data, "load_asset", lambda asset: [])

    assert bc.build_leaderboard(assets=["SOL"], top_n=15) == []


def test_dedups_identical_genomes(tmp_path, monkeypatch):
    g = lambda t: Genome("donchian_break", {"don": t, "atrN": 14, "atrMult": 3.0,
                                            "trail": 3, "erMin": 0.0, "regimeN": 20})
    # same genome twice + one distinct
    _seed_population(tmp_path, "SOL", [g(10), g(10), g(20)])

    class _R:
        def __init__(self, genome):
            self.genome = genome
            self.oos_t = float(genome.params["don"])
            self.oos_n = 50
            self.oos_mean = 0.01
            self.oos_p = 0.1

    monkeypatch.setattr(bc, "STATE_DIR", tmp_path)
    monkeypatch.setattr(bc.fitness, "evaluate", lambda genome, splits, alpha: _R(genome))
    monkeypatch.setattr(bc.data, "split", lambda bars: ([], []))
    monkeypatch.setattr(bc.data, "load_asset", lambda asset: [])

    board = bc.build_leaderboard(assets=["SOL"], top_n=15)
    assert len(board) == 2   # the duplicate scored once


def test_prior_candidate_ids_selects_only_nonsignificant_evolab(monkeypatch):
    import io
    runs = {"runs": [
        {"id": "a", "strategy": "evolab:donchian_break", "significant": False},  # candidate -> sweep
        {"id": "b", "strategy": "evolab:bollinger_break", "significant": True},   # champion -> keep
        {"id": "c", "strategy": "manual_paste", "significant": False},            # not evolab -> keep
        {"id": "d", "strategy": "evolab:ma_cross", "significant": False},         # candidate -> sweep
        {"id": "", "strategy": "evolab:ts_momentum", "significant": False},       # no id -> skip
    ]}

    class _Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): self.close()

    monkeypatch.setattr(bc.urllib.request, "urlopen",
                        lambda req, timeout=0: _Resp(json.dumps(runs).encode()))
    assert bc.prior_candidate_ids("http://x") == ["a", "d"]


def test_candidate_below_deflated_bar_is_not_significant(tmp_path, monkeypatch):
    # A t=2.1 genome looks "real" single-hypothesis, but pulled from a heavily
    # deflated search it must NOT be marked significant — the anti-Trader.dev rule.
    g = Genome("donchian_break", {"don": 42, "atrN": 14, "atrMult": 3.0,
                                  "trail": 3, "erMin": 0.0, "regimeN": 20})
    _seed_population(tmp_path, "SOL", [g])

    class _R:
        def __init__(self, genome):
            self.genome = genome
            self.oos_t = 2.1            # passes single-hypothesis, far below deflated bar
            self.oos_n = 50
            self.oos_mean = 0.01
            self.oos_p = 0.04

    monkeypatch.setattr(bc, "STATE_DIR", tmp_path)
    monkeypatch.setattr(bc.fitness, "evaluate", lambda genome, splits, alpha: _R(genome))
    monkeypatch.setattr(bc.data, "split", lambda bars: ([], []))
    monkeypatch.setattr(bc.data, "load_asset", lambda asset: [])
    # huge cumulative trial count -> deflated bar ~5+, well above t=2.1
    monkeypatch.setattr(bc.Store, "alpha_deflated", lambda self: 0.05 / 500_000)

    board = bc.build_leaderboard(assets=["SOL"], top_n=15)
    assert len(board) == 1
    assert board[0].deflated_significant is False
    assert board[0].deflated_t_bar >= 4.0
