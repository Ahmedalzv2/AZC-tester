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


import json

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


def test_genome_dict_round_trip():
    from evolab.store import genome_from_dict, genome_to_dict
    g = Genome("bollinger_fade", {"bb_n": 20, "bb_k": 2.0, "atrN": 14, "atrMult": 2.0, "rr": 1.5})
    assert genome_from_dict(genome_to_dict(g)) == g
