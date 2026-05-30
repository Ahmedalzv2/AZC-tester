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
