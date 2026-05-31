# Self-policing paper lanes + rejection registry — design

**Date:** 2026-05-31
**Status:** approved (brainstorm), implementing (staged).

## Problem / intent

Run two paper-automated strategy lanes — a **spot grid** (Alpaca paper crypto)
and a **futures perp** simulation — but wrap them in a lifecycle that judges each
daily and *retires failures into a permanent, queryable graveyard*. A failed
strategy is a **fair invalidation**: no auto-retune, no second-guessing. The
graveyard is durable memory so every future study/search auto-skips what's
already been disproven ("automatically rejected because it failed our test").

## Decisions (brainstorm)

- End state: **paper-automated bots** (real/simulated fills, no money).
- On failure: **dump + record only** — NO auto-retune (auto-retuning a failed
  strategy is the overfitting machine the whole project fights). "Fixing" = the
  operator registers a brand-new hypothesis, tested fresh.
- Invalidation = **forward stats + drawdown** (thresholds below).
- Spot grid venue: **Alpaca paper crypto** (BTC/USD; reuses execution/alpaca_client).
- Futures: **internal simulator**, crypto perps (Donchian trend + taker fee +
  funding). Expected to confirm fee/funding-walled = a clean recorded invalidation.

## Architecture (new `lanes/` package)

### 1. Rejection registry — `lanes/registry.py` + `lanes/rejected-strategies.jsonl`
Durable, machine-readable graveyard (committed — it IS the memory).
- `signature(kind, params, venue, asset) -> str` — stable short hash of the
  identity-defining fields, so the same dead config is recognised again.
- `register_rejection(kind, params, venue, asset, reason, metrics, date) -> str`
  — append one JSONL entry `{signature, kind, venue, asset, params, reason,
  metrics{net_r,t,max_dd,n}, date}`.
- `is_rejected(signature) -> (bool, entry|None)` — what every future study calls.
- `list_rejections()`.
- **Seeded** at creation with the playbook §3 known-dead strategies (5m FVG,
  crypto mean-rev, FX trend, published alpha factors, LTC-trend) so the graveyard
  is useful from day one.

### 2. Lifecycle evaluator — `lanes/lifecycle.py`
Pure, unit-testable. `evaluate(track) -> {action, reason, metrics}` where `track`
exposes `n_trades, days, net_r, hac_t, max_dd`.
- **Blow-up kill (any sample):** `max_dd <= -0.20` → invalidate "drawdown breach".
- **No-edge dump:** `(n_trades >= 30 or days >= 45) and net_r <= 0` → invalidate
  "no forward edge".
- else `continue`.
Thresholds in one constants block, easy to tune. On invalidate the lane is
stopped, positions flattened, and a rejection registered. (Promotion toward live
is the separate existing hard rule: forward HAC t ≥ 2 sustained.)

### 3. Spot-grid lane — `lanes/grid.py` (Alpaca paper crypto, BTC/USD)
Classic grid: N levels across a band around price; limit buys low / sells high;
capture oscillation. Reuses `execution/alpaca_client.py` (extended: crypto symbol
+ limit orders + open-order management). Realized grid P&L = its forward record.
Grid's known death (price trends out of band) is caught by the −20% kill.

### 4. Futures perp-sim lane — `lanes/perp_sim.py` (internal)
Runs Donchian trend on perp live data; fills simulated with taker fee + funding
rate; forward NAV logged. No broker/account/money.

### 5. Daily timer
One job: evaluate both lanes → retire failures (flatten + register) → else step
forward. **NOT auto-wired without explicit operator authorization** (autonomous
trading loop — same rule as the Alpaca ETF cron).

## Build sequence (staged, each committed + tested)
1. Registry + lifecycle core (self-policing engine).
2. Grid lane (Alpaca paper crypto).
3. Perp-sim lane (internal).
4. Wire the daily timer (authorized).

## Hard constraints
Paper/sim only, no real money. No auto-retune. Alpaca path stays paper-guarded.
New files + own files only; no touch to Hermes's working set. Registry is the
durable memory — committed, and complements (doesn't replace) playbook §3.

## Testing (TDD)
- registry: signature stability, register→is_rejected round-trip, dedup by signature.
- lifecycle: blow-up kill at any sample, no-edge dump after min sample, continue
  when young, continue when profitable, drawdown takes precedence.
- grid: level generation, fill→replenish accounting (mockable, no network).
- perp-sim: fee+funding applied, forward NAV accrual.

## Out of scope (now)
Promotion-to-live automation; non-crypto grid; multi-exchange grid.
