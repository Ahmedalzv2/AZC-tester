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


def test_available_assets_is_a_dict():
    assert isinstance(data.MARKETS, dict)
    assert "SOL" in data.MARKETS
