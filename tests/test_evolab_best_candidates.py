from __future__ import annotations

import io
import json
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from evolab import best_candidates as bc
from evolab import universe as uni
from evolab.genome import Genome
from evolab.store import genome_to_dict


def _g(don: int) -> Genome:
    return Genome("donchian_break", {"don": don, "atrN": 14, "atrMult": 3.0,
                                     "trail": 3, "erMin": 0.0, "regimeN": 20})


class _FakeStore:
    def __init__(self, pops, trials):
        self.pops, self._trials = pops, trials

    def load_state(self, asset):
        return {"population": self.pops.get(asset, [])}

    def cumulative_trials(self):
        return self._trials


class FakeUniverse(uni.Universe):
    """In-memory universe: populations + a score function keyed off the genome,
    so build_leaderboard ranking is deterministic without real price data."""
    name = "fake"
    interval = "1d"

    def __init__(self, pops, *, trials=1, oos_n=50):
        self._store = _FakeStore(pops, trials)
        self._oos_n = oos_n

    def store(self):
        return self._store

    def assets(self):
        return list(self._store.pops.keys())

    def load_split(self, asset):
        return ([], [])

    def score(self, genome, is_bars, oos_bars):
        # don value doubles as the t-stat; oos_n configurable to test the floor.
        return uni.ScoreResult(genome, float(genome.params["don"]),
                               self._oos_n, 0.01, 0.1)


def _pop(*dons):
    return [genome_to_dict(_g(d)) for d in dons]


def test_build_leaderboard_ranks_by_oos_t_and_caps_top_n():
    u = FakeUniverse({"SOL": _pop(10, 30), "XRP": _pop(20, 5)})
    board = bc.build_leaderboard(u, top_n=3)
    assert [c.oos_t for c in board] == [30.0, 20.0, 10.0]
    assert board[0].asset == "SOL" and board[1].asset == "XRP"


def test_build_leaderboard_drops_thin_oos():
    u = FakeUniverse({"SOL": _pop(99)}, oos_n=bc.fitness.MIN_OOS_TRADES - 1)
    assert bc.build_leaderboard(u, top_n=15) == []


def test_dedups_identical_genomes():
    u = FakeUniverse({"SOL": _pop(10, 10, 20)})  # 10 twice
    board = bc.build_leaderboard(u, top_n=15)
    assert len(board) == 2


def test_candidate_below_deflated_bar_is_not_significant():
    # t=3 passes single-hypothesis, but heavy lifetime trials lift the bar to ~5.2 > 3.
    u = FakeUniverse({"SOL": _pop(3)}, trials=500_000)
    board = bc.build_leaderboard(u, top_n=15)
    assert len(board) == 1
    assert board[0].deflated_significant is False
    assert board[0].deflated_t_bar >= 4.0


def test_high_t_above_low_bar_is_significant():
    # same t=3 but few trials -> bar floors at 2.0 -> significant
    u = FakeUniverse({"SOL": _pop(3)}, trials=1)
    board = bc.build_leaderboard(u, top_n=15)
    assert board[0].deflated_significant is True


def test_batch_multiple_testing_deflates_even_with_zero_lifetime_trials():
    # 30 configs scored with a fresh store (0 lifetime trials): the bar must still
    # deflate for the 30-way comparison, not sit at the single-look 2.0.
    u = FakeUniverse({"SOL": _pop(*range(3, 33))}, trials=0)  # 30 genomes, t=3..32
    board = bc.build_leaderboard(u, top_n=15)
    assert board[0].deflated_t_bar > 2.0  # deflated by the 30-config search


def test_prior_candidate_ids_filters_by_interval_and_significance(monkeypatch):
    runs = {"runs": [
        {"id": "a", "strategy": "evolab:donchian_break", "significant": False, "interval": "1d"},
        {"id": "b", "strategy": "evolab:bollinger_break", "significant": True, "interval": "1d"},   # champion
        {"id": "c", "strategy": "manual_paste", "significant": False, "interval": "1d"},            # not evolab
        {"id": "d", "strategy": "evolab:ma_cross", "significant": False, "interval": "4h"},          # crypto, other universe
        {"id": "e", "strategy": "evolab:ts_momentum", "significant": False, "interval": "1d"},
    ]}

    class _Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): self.close()

    monkeypatch.setattr(bc.urllib.request, "urlopen",
                        lambda req, timeout=0: _Resp(json.dumps(runs).encode()))
    # proven (1d) replace must NOT touch the crypto (4h) row 'd' or the champion 'b'
    assert bc.prior_candidate_ids("http://x", interval="1d") == ["a", "e"]
    # crypto (4h) replace touches only 'd'
    assert bc.prior_candidate_ids("http://x", interval="4h") == ["d"]
