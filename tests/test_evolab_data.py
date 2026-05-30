from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from engine_bracket import Bar
from evolab import data


def test_split_respects_oos_fraction():
    bars = [Bar(t=i, o=1.0, h=1.0, l=1.0, c=1.0) for i in range(100)]
    is_bars, oos_bars = data.split(bars, oos_fraction=0.30)
    assert len(is_bars) == 70
    assert len(oos_bars) == 30
    assert is_bars[-1].t == 69
    assert oos_bars[0].t == 70


def test_markets_constant_has_expected_assets():
    assert isinstance(data.MARKETS, dict)
    assert "SOL" in data.MARKETS


def test_available_assets_returns_subset_of_markets():
    # Robust regardless of which fixtures are mounted: empty list if none.
    avail = data.available_assets()
    assert isinstance(avail, list)
    assert set(avail).issubset(set(data.MARKETS))


def test_discovery_picks_deepest_tape_per_symbol():
    # SOL has both 1825d and 1095d mounted; the deeper (1825d) must win.
    fix = data.FIX
    if (fix / "SOL-1825d-Min60.json").exists():
        assert data.MARKETS["SOL"][0] == "SOL-1825d-Min60.json"


def test_discovery_widens_beyond_the_original_three():
    # The gateway was hardcoded to SOL/DOGE/XRP; auto-discovery must expose the
    # full mounted basket (BTC/ETH/etc.) when those fixtures are present.
    fix = data.FIX
    if (fix / "BTC-1095d-Min60.json").exists():
        assert "BTC" in data.MARKETS
        assert "BTC" in data.available_assets()
    # Whatever is mounted, every market entry must resolve to a real file.
    for sym, (fname, per) in data.MARKETS.items():
        assert (fix / fname).exists(), f"{sym} -> missing {fname}"
        assert per >= 1


def test_resample_period_is_4h_from_hourly():
    # All Min60 tapes are hourly; period 4 -> 4h bars (the AZC trade cadence).
    for sym, (fname, per) in data.MARKETS.items():
        if "Min60" in fname:
            assert per == 4
