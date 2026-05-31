# Alpaca paper-trading bridge — design

**Date:** 2026-05-31
**Status:** built (v1); daily timer deferred to explicit user authorization.

## Problem

The proven ETF trend portfolio's only real validation is a FORWARD track record
(playbook hard rule #1). The existing `etf_trend_paper.py` computes daily
portfolio returns from closes — frictionless, not broker-executed. This adds
GENUINE paper trades: real order submission to Alpaca's paper simulator, real
fills, no money. The honest forward proof, with execution drag included.

## Decisions

- **Venue:** Alpaca paper (free, instant keys, no KYC for paper, available to
  unsupported-country users as paper-only; verified UAE-viable). Pure REST SDK
  (`alpaca-py`) — cron-friendly, no terminal/MCP/CLI needed. ETFs (cash shares)
  avoid the CFD overnight-financing drag that would distort a long-hold trend.
- **Universe:** `portfolio_trend.DEFAULT_UNIVERSE` (SPY QQQ IWM EFA EEM GLD SLV
  DBC USO TLT), vol-targeted weights from `current_targets`.
- **Sizing:** notional (dollar) orders — Alpaca fractionalizes; no price lookups.

## Architecture (new `execution/` package)

- **`rebalance.py`** — PURE `plan_orders(targets, equity, positions, min_trade)`
  → abstract orders `{symbol, action: buy|sell|close, notional}`. Dropped/zero-
  weight holdings are CLOSED outright; sub-threshold deltas skipped (no churn).
  Fully unit-tested, no network.
- **`alpaca_client.py`** — `AlpacaPaper(dry_run)` over `TradingClient(paper=True)`.
  `equity()`, `positions()` (symbol→market value), `submit(order)`. **Hard
  paper-guard** `assert_paper(account_number, base_url)`: refuses to act unless
  the account has the `PA` prefix AND the endpoint is the paper one — live keys
  pasted by mistake raise instead of trading real money. Unit-tested.
- **`run_paper.py`** — daily runner: yahoo OHLC → `current_targets` → account →
  `plan_orders` → submit (fault-tolerant per order) → append NAV snapshot to
  `execution/alpaca-nav.jsonl` (gitignored runtime log). `--live-paper` to
  submit; **dry-run is the default**.

## Safety / constraints

- **Paper only**, hard-guarded structurally. No real money reachable.
- Dry-run default; `--live-paper` required to submit.
- Long-only ETF trend; leverage only as the vol-target emits (observed ~1.25× to
  hit 15% vol — faithful to the validated portfolio, within paper buying power).
- **No autonomous schedule installed without explicit user authorization** (the
  daily timer was intentionally NOT wired by the agent; user decides).

## Relationship to existing lane

`etf_trend_paper.py` stays as the frictionless theoretical benchmark; Alpaca is
the real-fill record. Gap between them = genuine execution drag — an honest metric.

## Verified (2026-05-31)

Keys connect to paper account `PA…`, $100k equity. Dry-run plans the 5-ETF buy
correctly. First `--live-paper` run submitted 5 orders, all `accepted`/queued
(market closed Sunday → fill at Mon 2026-06-01 open). 9 execution tests green.

## Tests (TDD)

- rebalance: flat→target, within-threshold no-op, reduce=sell delta, dropped=close,
  zero-weight=close, empty=no-op.
- guard: paper account+endpoint OK; non-PA account rejected; live endpoint rejected.

## Open / deferred

- **Daily timer** (Mon–Fri after US close, orders queue to next open) — pending
  explicit user go-ahead.
- Optional: reconcile vs `etf_trend_paper` to quantify execution drag.
