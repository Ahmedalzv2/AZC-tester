from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

import app as app_module

DEMO = str(Path(__file__).resolve().parents[1] / "sample_data" / "demo_ohlcv.parquet")


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKTEST_LAB_DB", str(tmp_path / "test_backtest_lab.duckdb"))


def _backtest_request() -> app_module.BacktestRequest:
    return app_module.BacktestRequest(
        data_provider="local_file",
        symbol="DEMO",
        interval="1d",
        file_path=DEMO,
        strategy="sma_cross",
        strategy_params={"fast": 10, "slow": 30},
        fee_bps=5,
    )


def test_backtest_is_saved_and_exposed_in_history() -> None:
    out = app_module.backtest(_backtest_request())
    assert out["run_id"]

    runs = app_module.runs(limit=10)
    assert len(runs["runs"]) == 1
    row = runs["runs"][0]
    assert row["id"] == out["run_id"]
    assert row["strategy"] == "sma_cross"
    assert row["provider"] == "local_file"
    assert row["metrics"]["trade_count"] >= 0

    detail = app_module.run_detail(out["run_id"])
    assert detail["result"]["metrics"]["strategy"] == "sma_cross"
    assert detail["request"]["file_path"] == DEMO


def test_compare_endpoint_returns_selected_runs() -> None:
    first = app_module.backtest(_backtest_request())
    second_req = _backtest_request()
    second_req.strategy_params = {"fast": 5, "slow": 20}
    second = app_module.backtest(second_req)

    out = app_module.compare_endpoint(app_module.CompareRequest(run_ids=[first["run_id"], second["run_id"]]))
    assert out["count"] == 2
    assert len(out["runs"]) == 2
    assert len(out["chart_series"]) == 2
    assert {row["id"] for row in out["runs"]} == {first["run_id"], second["run_id"]}


def test_dataset_access_log_is_populated() -> None:
    app_module.backtest(_backtest_request())
    out = app_module.datasets(limit=10)
    assert out["count"] == 1
    row = out["datasets"][0]
    assert row["provider"] == "local_file"
    assert row["rows"] > 0
    assert row["dataset"]["start"]
