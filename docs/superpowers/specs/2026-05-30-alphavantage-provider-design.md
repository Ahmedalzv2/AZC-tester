# AlphaVantage data provider for backtest-lab

**Date:** 2026-05-30
**Status:** Design — approved pending user spec review
**Author:** Claude Code (with Ahmed)

## Goal

Add AlphaVantage as a selectable data source in backtest-lab, plus a thin
cross-check layer that diffs the same symbol across providers. Purpose is the
lab's existing truth-layer mandate: catch silent Yahoo data errors and gain
deeper daily FX history than Yahoo gives.

## Constraints (the binding ones)

- **Free API key only.** 25 requests/day, 5/min. This is the whole design
  pressure. Daily history is fine (cache once per symbol per 12h). Intraday
  across a 25-symbol basket is not viable on free.
- Shared working tree with Hermes. New code is one new file plus a one-line
  registration; commits are path-scoped to avoid bundling others' uncommitted
  work. The active soft-lock is on the chart layer — untouched here.
- No new heavy deps. Add `requests` (already transitively present via yfinance).

## Scope

### In scope
1. `providers/alphavantage.py` — `AlphaVantageProvider(BaseDataProvider)`,
   same shape and caching discipline as `providers/yahoo.py`.
   - `FX_DAILY` (outputsize=full) → deep daily FX incl. GBPJPY.
   - `DIGITAL_CURRENCY_DAILY` → crypto daily.
   - `TIME_SERIES_DAILY` (outputsize=full) → equities/ETF, for completeness.
2. Registration in `providers/__init__.py`.
3. `requests` added to `requirements.txt`.
4. `env_file`/`environment` in `docker-compose.yml` so the container sees
   `ALPHAVANTAGE_API_KEY` (key itself NOT committed).
5. `data_check.py` — `cross_check_history(symbol, interval, providers)` thin
   utility returning close-price divergence stats between two providers.
6. Unit tests with recorded JSON fixtures (no live calls in CI).

### Out of scope (free-key reality, deferred not deleted)
- Basket-wide intraday. `FX_INTRADAY`/`CRYPTO_INTRADAY` are wired but
  **guarded**: on a free key they raise a clear `DataSourceError` directing the
  user to set a premium flag. Turning them on later is relaxing one guard, not
  a rewrite.
- A `/api/datacheck` HTTP endpoint + dashboard panel. The `data_check.py`
  function lands now; surfacing it in the UI is a follow-up plan.

## Architecture

`AlphaVantageProvider` mirrors `YahooFinanceProvider`:

- `name = "alphavantage"`, `family = "remote_api"`, `supports_remote = True`.
- `asset_classes = ["fx", "crypto", "stocks", "etf"]`.
- `supported_intervals = ["1d", "1wk", "1mo", "5m", "15m", "30m", "60m"]`
  (intraday values present but guarded).
- Cache: reuse `CACHE_DIR`, filename
  `{safe_symbol}_{interval}_alphavantage.csv`, 12h-stale logic copied from
  Yahoo. Caching is what keeps daily pulls inside 25/day.
- Output normalizes through the existing `BaseDataProvider.ensure_ohlcv`, so
  the rest of the lab (engine, sweep, stats) sees identical OHLCV frames
  regardless of source.

### The three real problems (not boilerplate)

1. **Symbol mapping.** The lab uses Yahoo-style tickers; AlphaVantage uses
   different argument shapes per asset class. A `_resolve_symbol(symbol)`
   helper classifies and maps:
   - FX: `GBPJPY=X`, `GBPJPY`, `GBP/JPY` → `from_symbol=GBP, to_symbol=JPY`,
     function `FX_DAILY`.
   - Crypto: `BTC-USD`, `BTCUSD`, `BTC/USD` → `symbol=BTC, market=USD`,
     function `DIGITAL_CURRENCY_DAILY`.
   - Else: treat as equity/ETF symbol, function `TIME_SERIES_DAILY`.
   - Ambiguous/unmappable → `DataSourceError` raised before any network call.

2. **Error-as-HTTP-200.** AlphaVantage returns quota/rate/bad-symbol messages
   as HTTP 200 JSON with `Note`, `Information`, or `Error Message` keys (no
   time-series payload). `_extract_series` checks for these keys first and
   raises `DataSourceError` with the upstream message, so the rate-limit case
   surfaces honestly instead of feeding `ensure_ohlcv` an empty frame.

3. **Per-endpoint schema.**
   - `FX_DAILY`: keys `"Time Series FX (Daily)"`, fields `1. open`..`4. close`,
     no volume → `ensure_ohlcv` fills `Volume=0`.
   - `DIGITAL_CURRENCY_DAILY`: AlphaVantage's current simplified schema
     (`1. open`/`2. high`/`3. low`/`4. close`/`5. volume` in the market
     currency). Handle the current schema; if the legacy dual-currency
     `4a./4b.` keys appear, prefer the `*b.`/USD-market columns.
   - `TIME_SERIES_DAILY`: keys `"Time Series (Daily)"`, standard OHLCV.
   - All three parse into a DataFrame and hand off to `ensure_ohlcv`.

### Cross-check utility

`data_check.py`:

```
cross_check_history(symbol, interval="1d",
                    providers=("yahoo", "alphavantage")) -> dict
```

- Fetches the symbol from both providers via the existing
  `data_source.fetch_history`.
- Inner-joins on the shared date index.
- Returns: overlap row count, date range, per-provider row counts,
  `max_abs_close_pct`, `mean_abs_close_pct`, count of bars diverging beyond a
  threshold (default 0.5%), and the worst N offending dates.
- Pure function, no I/O of its own beyond the providers; trivially testable
  with two fixture frames.

## Config / secrets

- `ALPHAVANTAGE_API_KEY` read from `os.environ` at fetch time (matches the
  existing `os.environ` config style in `storage.py`).
- Missing key → `DataSourceError("Set ALPHAVANTAGE_API_KEY")` before any call.
- `ALPHAVANTAGE_PREMIUM` (truthy) relaxes the intraday guard later.
- `docker-compose.yml` gets an `env_file` pointing at an uncommitted
  `.env`/`relay.env`-style file; key never enters git.

## Error handling

- Missing key, unmappable symbol, intraday-on-free, and upstream
  `Note`/`Information`/`Error Message` all raise `DataSourceError` with a
  specific, actionable message.
- Network/JSON-decode failures wrapped in `DataSourceError`.
- `ensure_ohlcv` already rejects empty/closeless frames downstream.

## Testing

Recorded JSON fixtures under `tests/fixtures/alphavantage/` (no live network in
CI). Cases:

- FX daily parse → correct OHLCV, Volume filled to 0.
- Crypto daily parse (current schema) → correct OHLCV.
- Equity daily parse → correct OHLCV.
- Symbol mapping: `GBPJPY=X`/`BTC-USD`/`SPY` resolve to the right
  function+args; unmappable raises.
- Each of the three error-key responses raises `DataSourceError`.
- Missing `ALPHAVANTAGE_API_KEY` raises before any HTTP.
- Intraday interval on free key raises the guard error.
- `cross_check_history` on two crafted frames returns expected divergence
  stats and handles non-overlapping ranges.
- `test_providers_metadata.py` extended so the new provider's `describe()`
  is covered.

## Non-goals

- No change to default provider or per-asset-class routing. AlphaVantage is an
  additional selectable source; cross-check is opt-in.
- No retry/backoff scheduler for the 25/day budget — caching + manual
  incremental pulls are enough at this scale. Revisit only with a premium key.

## Open questions

None blocking. Premium-tier behavior is stubbed behind `ALPHAVANTAGE_PREMIUM`
and can be fleshed out when/if a key is bought.
