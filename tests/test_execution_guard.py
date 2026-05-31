from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from execution.alpaca_client import assert_paper


def test_paper_account_on_paper_endpoint_ok():
    assert_paper("PA3C1234", "BaseURL.TRADING_PAPER") is None  # no raise


def test_live_account_number_rejected():
    with pytest.raises(RuntimeError):
        assert_paper("1234ABCD", "BaseURL.TRADING_PAPER")  # no PA prefix


def test_live_endpoint_rejected():
    with pytest.raises(RuntimeError):
        assert_paper("PA3C1234", "https://api.alpaca.markets")  # live endpoint
