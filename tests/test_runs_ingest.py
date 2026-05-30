import importlib


def test_ingest_persists_and_lists(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKTEST_LAB_DB", str(tmp_path / "t.duckdb"))
    import storage
    importlib.reload(storage)
    import app
    importlib.reload(app)

    req = app.IngestRequest(
        request_payload={"strategy": "evolab:rsi_reversion", "data_provider": "azc_fixture",
                         "symbol": "SOL", "interval": "4h", "years": 0, "strategy_params": {"rsi_n": 14}},
        response_payload={"metrics": {"trade_count": 5, "total_return_pct": 3.2},
                          "significance": {"tstat": 2.4, "pvalue": 0.01, "significant": True}},
    )
    out = app.ingest_run(req)
    run_id = out["run_id"]
    assert run_id

    rows = storage.list_runs()
    match = [r for r in rows if r["id"] == run_id]
    assert match and match[0]["strategy"] == "evolab:rsi_reversion"
    assert match[0]["significance"]["significant"] is True
