from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

import evolab_api


def _seed_state(state_dir: Path):
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "trials.json").write_text(json.dumps({"cumulative": 200}))
    (state_dir / "SOL.json").write_text(json.dumps({
        "asset": "SOL", "generation": 5, "population": [], "champion": None,
    }))
    (state_dir / "DOGE.json").write_text(json.dumps({
        "asset": "DOGE", "generation": 3, "population": [],
        "champion": {"family": "ts_momentum", "params": {"mom": 20}, "oos_t": 2.4, "oos_p": 0.001},
    }))
    (state_dir / "runs.jsonl").write_text(
        json.dumps({"asset": "SOL", "best_is_score": 0.42, "ts": 111}) + "\n" +
        json.dumps({"asset": "DOGE", "best_is_score": 0.88, "ts": 222}) + "\n"
    )
    (state_dir / "daemon.json").write_text(json.dumps({"last_cycle_ts": 999, "cycle": 7}))


def test_evolab_state_shape(tmp_path):
    _seed_state(tmp_path)
    out = evolab_api.evolab_state(tmp_path)
    assert out["cumulative_trials"] == 200
    assert abs(out["alpha_deflated"] - 0.05 / 200) < 1e-12
    assert out["daemon"]["cycle"] == 7
    by_asset = {a["asset"]: a for a in out["assets"]}
    assert by_asset["SOL"]["champion"] is None
    assert by_asset["SOL"]["best_is_score"] == 0.42
    assert by_asset["DOGE"]["champion"]["family"] == "ts_momentum"
    assert by_asset["DOGE"]["best_is_score"] == 0.88


def test_missing_files_degrade_gracefully(tmp_path):
    # Empty dir -> no 500, just zeros/empties.
    out = evolab_api.evolab_state(tmp_path)
    assert out["cumulative_trials"] == 0
    assert out["daemon"] is None
    assert out["assets"] == []


def test_verdict_rejects_unknown_asset():
    import pytest
    from fastapi import HTTPException
    req = evolab_api.VerdictRequest(family="donchian_break", params={}, asset="NOPE")
    with pytest.raises(HTTPException) as exc:
        evolab_api.post_verdict(req)
    assert exc.value.status_code == 400
