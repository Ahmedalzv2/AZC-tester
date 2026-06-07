"""Tests for the live shadow-lane significance tracker."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import live_significance as ls


def _write(tmp: Path, records: list[dict]) -> Path:
    p = tmp / "trend-signals.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return p


def test_empty_log_reports_accumulating(tmp_path):
    p = tmp_path / "nope.jsonl"
    out = ls.lane_significance(p)
    assert out["trades_resolved"] == 0
    assert out["significant"] is False
    assert "accumulating" in out["status"]
    assert out["log_present"] is False


def test_resolved_exits_drive_significance(tmp_path):
    # Strong, consistent positive edge -> should clear |t|>=2.
    day = 24 * 3600 * 1000
    records = []
    for i in range(40):
        records.append({"ts": i * day, "decision": "entry", "dir": "long"})
        records.append({"ts": i * day + 1000, "decision": "exit", "win": True, "netR": 0.5})
    # a few losers so it's not degenerate
    for i in range(40, 50):
        records.append({"ts": i * day, "decision": "exit", "win": False, "netR": -0.3})
    p = _write(tmp_path, records)
    out = ls.lane_significance(p)
    assert out["trades_resolved"] == 50
    assert out["entries"] == 40
    assert out["mean_netR"] > 0
    assert out["tstat"] > 2.0
    assert out["significant"] is True
    assert out["trades_per_week"] > 0


def test_skip_records_counted_not_traded(tmp_path):
    records = [
        {"ts": 0, "decision": "skip", "reason": "chop"},
        {"ts": 1000, "decision": "skip", "reason": "chop"},
        {"ts": 2000, "decision": "entry", "dir": "short"},
    ]
    out = ls.lane_significance(_write(tmp_path, records))
    assert out["skips_chop"] == 2
    assert out["trades_resolved"] == 0
    assert out["entries"] == 1
