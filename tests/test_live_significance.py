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


def test_same_bar_cluster_deflates_significance(tmp_path):
    # 26 winning exits crammed into 2 bars = 2 independent events, not 26.
    # Per-trade t looks huge; cluster-level evidence is nowhere near t>=2.
    records = []
    for i in range(26):
        bar = 4 * 3600 * 1000 * (1 if i < 13 else 2)
        records.append({"ts": bar + i, "barTs": bar, "decision": "exit",
                        "win": True, "netR": 0.9 + (i % 3) * 0.1, "symbol": f"S{i}"})
    out = ls.lane_significance(_write(tmp_path, records))
    assert out["cluster"]["n_bars"] == 2
    assert out["significant"] is False
    assert "CONFIRMED" not in out["status"]


def test_open_positions_stress_gates_significance(tmp_path):
    # 12 resolved winners across independent bars would clear t>=2 alone,
    # but 10 still-open positions marked at -0.5R must hold the flag down.
    bar = 4 * 3600 * 1000
    records = []
    for i in range(12):
        records.append({"ts": i * bar + 500, "barTs": i * bar, "decision": "exit",
                        "win": True, "netR": 0.45 + (i % 2) * 0.1, "symbol": f"W{i}"})
    for j in range(10):
        records.append({"ts": (20 + j) * bar, "barTs": (20 + j) * bar,
                        "decision": "entry", "dir": "long", "symbol": f"O{j}"})
    out = ls.lane_significance(_write(tmp_path, records))
    assert out["open_positions"]["count"] == 10
    assert out["cluster"]["tstat"] > 2.0  # resolved-only evidence is strong...
    assert out["significant"] is False    # ...but opens-at-risk veto the flag
    no_opens = [r for r in records if r["decision"] == "exit"]
    assert ls.lane_significance(_write(tmp_path, no_opens))["significant"] is True


def test_restart_duplicate_entries_not_counted_open(tmp_path):
    # Crash-restart loops re-log the same entry; an exit closes the symbol's
    # position regardless of how many duplicate entry rows precede it.
    bar = 4 * 3600 * 1000
    records = [
        {"ts": 1, "barTs": bar, "decision": "entry", "dir": "long", "symbol": "BNB"},
        {"ts": 2, "barTs": bar, "decision": "entry", "dir": "long", "symbol": "BNB"},
        {"ts": 3, "barTs": bar, "decision": "entry", "dir": "long", "symbol": "BNB"},
        {"ts": 4, "barTs": 2 * bar, "decision": "exit", "win": True, "netR": 0.4, "symbol": "BNB"},
        {"ts": 5, "barTs": 2 * bar, "decision": "entry", "dir": "short", "symbol": "APT"},
    ]
    out = ls.lane_significance(_write(tmp_path, records))
    assert out["open_positions"]["count"] == 1
    assert out["open_positions"]["symbols"] == ["APT"]
