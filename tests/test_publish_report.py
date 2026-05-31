"""The gallant report renderer fills its rich sections only when an ingested run
carries `metrics.report` AND dollar-shaped trades. EvoLab used to ship neither
(R-native trades + a report-less metrics block), so every candidate opened to an
empty Strategy Report. These tests pin the producer-side fix: the publisher must
attach a full report and ship dollar-denominated trades."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from evolab.publish import _assemble_payload, build_dollar_trades, build_equity_curve
from evolab.genome import Genome


def _genome() -> Genome:
    return Genome(family="donchian_break", params={"riskPct": 0.01})


def _verdict() -> dict:
    return {
        "verdict": "noise",
        "net_R_oos": 0.1,
        "is": {"n": 50, "meanR": 0.01, "t": 1.0},
        "oos": {"n": 40, "meanR": 0.02, "t": 1.2, "p": 0.1},
    }


def _trades() -> list[dict]:
    # The enriched shape simulate_signal now emits (grossR/entry/exit/bars/exit_ts
    # carried alongside the original ts/dir/netR/win).
    return [
        {"ts": 1000, "dir": "long", "netR": 1.0, "win": True,
         "grossR": 1.1, "entry": 100.0, "exit": 110.0, "bars": 5, "exit_ts": 6000},
        {"ts": 7000, "dir": "short", "netR": -0.5, "win": False,
         "grossR": -0.4, "entry": 110.0, "exit": 115.0, "bars": 3, "exit_ts": 10000},
        {"ts": 11000, "dir": "long", "netR": 0.5, "win": True,
         "grossR": 0.6, "entry": 108.0, "exit": 112.0, "bars": 4, "exit_ts": 15000},
    ]


def test_assemble_attaches_populated_report():
    _, resp = _assemble_payload("SOL", _genome(), _trades(), _verdict())
    rep = resp["metrics"].get("report")
    assert rep, "ingested run must carry metrics.report or the renderer blanks"
    assert rep["total_trades"] == 3
    assert rep["splits"]["long"]["trades"] == 2
    assert rep["splits"]["short"]["trades"] == 1
    assert rep["distribution"]["counts"], "distribution histogram must be populated"
    # report reconciles with the equity curve the same payload ships
    assert rep["ending_equity"] == pytest.approx(resp["curve"][-1]["equity"], abs=0.01)


def test_shipped_trades_are_dollar_shaped_and_fee_honest():
    _, resp = _assemble_payload("SOL", _genome(), _trades(), _verdict())
    t0 = resp["trades"][0]
    for k in ("side", "net_pnl", "gross_pnl", "commission", "pnl_pct", "cum_pnl"):
        assert k in t0, f"blotter needs {k}"
    # commission is the honest gross-vs-net gap, never silently zero when fees bite
    assert t0["gross_pnl"] != t0["net_pnl"]
    assert t0["commission"] == pytest.approx(t0["gross_pnl"] - t0["net_pnl"], abs=1e-6)


def test_dollar_ledger_matches_additive_curve():
    trades, risk = _trades(), 0.01
    dt = build_dollar_trades(trades, risk)
    curve = build_equity_curve([t["netR"] for t in trades], risk)
    # cumulative net P&L must track the additive equity index the chart draws
    assert dt[-1]["cum_pnl"] == pytest.approx(curve[-1]["equity"] - 100.0, abs=1e-6)


def test_dollar_ledger_tolerates_pre_enrichment_trades():
    # Trades from other callers (shadow lanes) lack grossR/entry; must not crash.
    bare = [{"ts": 1, "dir": "long", "netR": 0.3, "win": True}]
    dt = build_dollar_trades(bare, 0.01)
    assert dt[0]["gross_pnl"] == pytest.approx(dt[0]["net_pnl"], abs=1e-9)
    assert dt[0]["commission"] == pytest.approx(0.0, abs=1e-9)
