# Backtest Lab

Fast local dashboard for generic strategy research, with a full TradingView-style
**strategy report**.

What it does:
- runs a market-agnostic backtest engine against normalized OHLCV data
- uses pluggable data providers instead of hard-coding one market/feed
- caches Yahoo datasets locally under `data_cache/`
- loads local CSV or Parquet files directly by path
- supports built-in strategies and custom Python strategy logic
- serves a browser dashboard: summary cards, equity + drawdown curve, returns
  split (ALL / LONG / SHORT), profit structure, risk-adjusted ratios
  (Sharpe / Sortino / max run-up), win-loss donut, P&L distribution, a full
  performance-details table, and a detailed trade list

Strategy report (`metrics.report`):
- Every `/api/backtest` response carries a `report` block, built by `report.py`
  from the equity curve + the per-trade dollar ledger. Both execution engines
  (close-to-close `engine.py` and the AZC bracket `engine_bracket.py`) feed the
  same shape, so the report renders identically regardless of lane.
- Profit structure is exact: `gross_profit + gross_loss - commission == net_pnl`.
- Trades carry dollar truth: side, entry/exit price+time, qty, bars, net/gross
  P&L, commission, cumulative P&L, and per-trade run-up / drawdown.

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

## Authentication

The compute/mutating endpoints execute strategy code, so they are gated by a
shared secret when `AZC_API_KEY` is set in the server environment:

- Protected (require header `X-API-Key: <key>`): `POST /api/backtest`,
  `POST /api/sweep`, `POST /api/walkforward`, `DELETE /api/runs/{id}`.
- Open: the static UI, `GET /api/health`, `GET /api/strategies`,
  `GET /api/providers`, `GET /api/runs`, `GET /api/runs/{id}`.
- If `AZC_API_KEY` is unset, auth is disabled (local dev). **Always set it on
  any internet-facing deploy** — `custom_python` runs arbitrary Python.
- The browser UI prompts for the key once and stores it in `localStorage`.

Set it via docker-compose (host env or `.env`): `AZC_API_KEY=your-long-secret`.

## Feeding strategies programmatically (AZC integration)

The AZC platform feeds strategies by POSTing to `/api/backtest`. Each run is
auto-saved and appears in Browse. The response carries the full report plus the
honest edge signals to learn from: `significance` (`real`/`noise`,
Newey-West t + bootstrap p). For an out-of-sample check, POST the same body to
`/api/walkforward` and read `holds_out_of_sample` + `decay`.

Built-in strategy (curl):
```bash
curl -s https://HOST/api/backtest \
  -H "Content-Type: application/json" -H "X-API-Key: $AZC_API_KEY" \
  -d '{"data_provider":"yahoo","symbol":"BTC-USD","interval":"1d","years":5,
       "strategy":"sma_cross","strategy_params":{"fast":10,"slow":30},
       "initial_cash":10000,"fee_bps":7}'
```

Custom strategy — send the logic as a `build_signals(df, params)` function in
`custom_code` (return a position series in [-1, 1]; +1 long, -1 short, 0 flat):
```json
{
  "data_provider": "yahoo",
  "symbol": "BTC-USD",
  "interval": "1d",
  "years": 5,
  "strategy": "custom_python",
  "strategy_params": {"lookback": 20},
  "custom_code": "def build_signals(df, params):\n    n = int(params.get('lookback', 20))\n    ma = df['Close'].rolling(n).mean()\n    return (df['Close'] > ma).astype(float)\n",
  "initial_cash": 10000,
  "fee_bps": 7
}
```

Response keys an AZC learning loop cares about:
- `metrics.total_return_pct`, `metrics.report.profit_factor`,
  `metrics.report.sharpe`, `metrics.report.sortino`, `metrics.report.max_drawdown_pct`
- `significance.significant` (bool), `significance.tstat`, `significance.pvalue`
- `saved.id` — the run id, openable in Browse / `GET /api/runs/{id}`
