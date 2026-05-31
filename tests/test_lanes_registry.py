from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from lanes import registry


def test_signature_is_stable_and_param_order_independent():
    a = registry.signature("grid", {"levels": 10, "band": 0.05}, "alpaca", "BTC/USD")
    b = registry.signature("grid", {"band": 0.05, "levels": 10}, "alpaca", "BTC/USD")
    assert a == b  # param dict order must not change the signature


def test_signature_differs_on_meaningful_change():
    a = registry.signature("grid", {"levels": 10}, "alpaca", "BTC/USD")
    assert a != registry.signature("grid", {"levels": 20}, "alpaca", "BTC/USD")
    assert a != registry.signature("grid", {"levels": 10}, "alpaca", "ETH/USD")
    assert a != registry.signature("perp", {"levels": 10}, "alpaca", "BTC/USD")


def test_register_then_is_rejected_roundtrip(tmp_path):
    p = tmp_path / "rej.jsonl"
    sig = registry.register_rejection(
        "grid", {"levels": 10}, "alpaca", "BTC/USD",
        reason="no forward edge", metrics={"net_r": -0.2, "max_dd": -0.24, "n": 40},
        date="2026-06-12", path=p)
    hit, entry = registry.is_rejected(sig, path=p)
    assert hit is True
    assert entry["reason"] == "no forward edge"
    assert entry["kind"] == "grid" and entry["asset"] == "BTC/USD"


def test_unknown_signature_not_rejected(tmp_path):
    p = tmp_path / "rej.jsonl"
    registry.register_rejection("grid", {"levels": 10}, "alpaca", "BTC/USD",
                                reason="x", metrics={}, date="2026-06-12", path=p)
    hit, entry = registry.is_rejected("deadbeef", path=p)
    assert hit is False and entry is None


def test_is_rejected_on_missing_file_is_false(tmp_path):
    hit, entry = registry.is_rejected("anything", path=tmp_path / "nope.jsonl")
    assert hit is False and entry is None
