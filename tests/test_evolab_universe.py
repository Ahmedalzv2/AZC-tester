from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from engine_bracket import Bar
from evolab import universe as uni
from evolab.genome import Genome


def _trending_daily(n: int, drift: float) -> list[Bar]:
    bars, px = [], 100.0
    day = 24 * 3600_000
    for i in range(n):
        px *= (1 + drift)
        bars.append(Bar(t=i * day, o=px, h=px * 1.01, l=px * 0.99, c=px))
    return bars


def test_proven_fee_is_2bp_not_crypto():
    assert uni.PROVEN_FEE["takerRate"] == 0.0002          # 2bp
    assert uni.data.TAKER["takerRate"] == 0.00075          # crypto 7.5bps, untouched


def test_universes_have_separate_state_dirs():
    # Deflation isolation: proven must NOT share crypto's trial counter / state.
    assert uni.PROVEN.state_dir != uni.CRYPTO.state_dir
    assert uni.PROVEN.state_dir.name == "state-proven"


def test_proven_interval_is_daily():
    assert uni.PROVEN.interval == "1d"
    assert uni.CRYPTO.interval == "4h"


def test_proven_score_returns_oos_stats(monkeypatch):
    bars = _trending_daily(800, 0.002)
    monkeypatch.setattr(uni.ProvenUniverse, "load_asset", lambda self, asset: bars)
    is_bars, oos_bars = uni.data.split(bars)
    g = Genome("donchian_break", {"don": 50, "atrN": 14, "atrMult": 2.0,
                                  "trail": 5, "erMin": 0.0, "regimeN": 20})
    r = uni.PROVEN.score(g, is_bars, oos_bars)
    assert r.oos_n >= 0 and r.oos_t == r.oos_t  # finite, not NaN


def test_proven_build_payload_shape(monkeypatch):
    bars = _trending_daily(800, 0.002)
    monkeypatch.setattr(uni.ProvenUniverse, "load_asset", lambda self, asset: bars)
    g = Genome("donchian_break", {"don": 50, "atrN": 14, "atrMult": 2.0,
                                  "trail": 5, "erMin": 0.0, "regimeN": 20})
    req, resp = uni.PROVEN.build_payload("GSPC", g)
    assert req["symbol"] == "GSPC"
    assert req["interval"] == "1d"
    assert req["data_provider"] == "yahoo_daily"
    assert resp["metrics"]["fee_bps"] == 2.0
    assert resp["metrics"]["fee_model"] == "2bp-taker"
    assert resp["significance"]["significant"] is False        # overridden later, default honest
    assert resp["evolab"]["universe"] == "proven"


def test_get_unknown_universe_raises():
    import pytest as _pytest
    with _pytest.raises(KeyError):
        uni.get("forex")
