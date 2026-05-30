# Backtest Lab

Fast local dashboard for generic strategy research.

What it does:
- runs a market-agnostic backtest engine against normalized OHLCV data
- uses pluggable data providers instead of hard-coding one market/feed
- caches Yahoo datasets locally under `data_cache/`
- loads local CSV or Parquet files directly by path
- supports built-in strategies and custom Python strategy logic
- serves a browser dashboard for charts, metrics, and future extensions

Current data providers:
- `yahoo` — first remote adapter, still honest about intraday retention limits
- `local_file` — reads `.csv` and `.parquet` from VPS paths

Current strategy modules:
- `strategies/trend_trail.py` — current AZC trend-follow + chandelier-trail lane
- `strategies/sma_cross.py`
- `strategies/rsi_reversion.py`
- `strategies/breakout.py`
- `strategies/custom_python.py`

Notes:
- Full 5-year history is reliable on daily bars.
- Intraday history is limited by the upstream Yahoo data source. The app trims requests when the source cannot provide 5 years at that interval.
- Local file imports expect OHLCV-style columns. `Close` is required. If `Open`/`High`/`Low` are missing they are backfilled from `Close`.
- Custom strategy code runs locally on this VPS. It is flexible, not hardened sandbox security.

Run locally:
- `.venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 3015`
- open `http://127.0.0.1:3015`

Significance layer:
- Every `/api/backtest` response carries a `significance` block: Newey-West (HAC)
  t-stat of the mean return + a one-sided bootstrap p-value for "edge > 0".
- A run is flagged `significant` only when `|t| >= 2` and `p < 0.05`. This is the
  lesson from the AZC trend lane: a great equity curve with a weak t-stat is noise.

Parameter sweep:
- `POST /api/sweep` grids every combination of a parameter grid, attaches the
  significance verdict to each, and returns the table sorted best-first.
- The dashboard renders the ranked table with a per-row real/noise verdict so the
  top of the grid can be sanity-checked, not just celebrated.

API shape:
- `GET /api/health`
- `GET /api/providers`
- `GET /api/strategies`
- `POST /api/backtest`  — now includes a `significance` block
- `POST /api/sweep`     — grid search + per-combo significance, ranked best-first

Example sweep payload:
```json
{
  "data_provider": "local_file",
  "symbol": "DEMO",
  "interval": "1d",
  "file_path": "/root/apps/backtest-lab/sample_data/demo_ohlcv.parquet",
  "strategy": "sma_cross",
  "grid": {"fast": [5, 10, 20], "slow": [30, 50, 100]},
  "sort_by": "total_return_pct",
  "fee_bps": 5
}
```

Example local-file payload:
```json
{
  "data_provider": "local_file",
  "symbol": "DEMO",
  "interval": "1d",
  "years": 5,
  "file_path": "/root/apps/backtest-lab/sample_data/demo_ohlcv.parquet",
  "strategy": "sma_cross",
  "strategy_params": {"fast": 10, "slow": 30},
  "initial_cash": 10000,
  "fee_bps": 5
}
```
