# EvoLab → Browse bridge + per-prompt runner — design

**Date:** 2026-05-30
**Target instance:** main `backtest-lab` on :3015 (`backtest.srv1688368.hstgr.cloud`)
**Status:** approved design, pre-implementation

## Problem

EvoLab's strategy search never appears in the tester's Browse dashboard. The
daemon (`python -m evolab.daemon`) runs backtests **in-process** via
`bracket_signals.simulate_signal` and writes only to its own store
(`evolab/state/*.json`, `runs.jsonl`). The Browse dashboard reads a **separate**
DuckDB run-store (`storage/backtest_lab.duckdb`), populated only when a backtest
goes through the HTTP handlers (`/api/backtest|sweep|walkforward` → `save_run`).
The two stores are disjoint, so EvoLab results bypass Browse entirely.

We want two things:

1. **Per-prompt immediate feedback.** Operator pastes a strategy prompt; it is
   run once and shows in Browse right away, **and** is seeded into EvoLab's
   ongoing search.
2. **Champion bridge.** When EvoLab promotes a validated champion (clears the
   deflated-OOS gate), that champion is published to Browse — champions only,
   not the ~127k fitness trials.

## Constraints (hard)

- **Soft-lock:** `engine_bracket.py` and `static/*` (Chart.js migration) are
  Hermes's locked lane — **must not edit**. Work stays in `evolab/`,
  `storage.py`, `app.py`, `bracket_signals.py` (Claude's lane).
- **Fidelity:** the tester's `engine_bracket.simulate_bracket` is Donchian-baked
  and NOT generic over signal families. EvoLab uses its own generic
  `bracket_signals.simulate_signal(bars, SIGNALS[family], params)`. A champion
  must therefore be reproduced through EvoLab's own simulator, not re-run via
  `/api/backtest` as a named tester strategy.
- **DuckDB is single-writer across processes.** The daemon is a separate host
  systemd process; the API runs inside the container. Both map the same
  `storage/backtest_lab.duckdb` over the bind mount. The daemon must **not** open
  the DB directly — writes are routed through the API process.

## Chosen approach (A — EvoLab-side publisher)

Build the Browse payload in EvoLab's lane using EvoLab's own simulator; route the
DB write through the API via a thin authenticated ingest endpoint so DuckDB stays
single-writer.

### Components

1. **`evolab/publish.py` — `build_run_payload(asset, genome) -> (request, response)`**
   - Loads the asset's bars (`evolab.data.load_asset`), runs
     `simulate_signal(bars, SIGNALS[genome.family], params)` over full history
     and over the IS/OOS split (same split logic the search uses).
   - Metrics from the public `engine_bracket.bracket_metrics(trades)` (imported,
     read-only — no edit to the locked file). Significance from
     `stats.newey_west_tstat` / `stats.bootstrap_pvalue` on per-trade `netR`,
     matching how `fitness.py` scores.
   - Returns a `(request_payload, response_payload)` pair shaped for `save_run`:
     `request_payload` has `strategy="evolab:<family>"`, `data_provider="azc_fixture"`,
     `symbol=<asset>`, `interval`, `strategy_params=<genome.params>`;
     `response_payload` carries `metrics` + `significance` (the fields
     `storage._pick_preview` reads) plus the raw trades for the result detail.
   - Pure compute; no DB, no network. Independently testable.

2. **`POST /api/runs/ingest` in `app.py`**
   - Auth-guarded (`Depends(require_api_key)`, same as the other write routes).
   - Body: `{request_payload, response_payload}`. Calls
     `save_run("backtest", request_payload, response_payload)`; returns `{run_id}`.
   - Keeps the API process the **only** DuckDB writer.

3. **`evolab/publish.py` CLI — `python -m evolab.publish <ASSET> --family <f> --params '{…}' [--seed] [--no-publish]`**
   - Builds the payload and POSTs it to `http://127.0.0.1:3015/api/runs/ingest`
     (immediate Browse row); prints the `run_id`.
   - `--seed`: injects the genome into `evolab/state/<ASSET>.json` population
     (via a new `store.seed_genome`) so the daemon evolves it.
   - This is the entry the operator drives per pasted prompt.

4. **`store.seed_genome(asset, genome)`**
   - Atomically loads state, prepends/inserts the genome into `population`
     (respecting pop cap and dropping exact-duplicate genomes), saves via
     `write_json_atomic`. Lives in `evolab/store.py`.

5. **Daemon hook — `evolab/daemon.py`**
   - After `run_search`, if `result["new_champion"]`, build the champion's
     payload and POST to ingest. Env-gated `EVOLAB_PUBLISH=1` (default on),
     wrapped in try/except so a publish failure logs and the search loop
     continues. Reads `AZC_API_KEY` (env / main `.env`) for the POST when auth
     is on (main currently runs auth-off).

### Dedup & marking

- `evolab/state/published.json` records the last published champion signature
  per asset (`family` + sorted `params` + `is_score`). A champion publishes once
  per promotion, never every 30s cycle.
- All EvoLab-sourced rows carry `strategy="evolab:<family>"` and a title like
  `evolab:<family>:<ASSET>`, so Browse can distinguish them from manual runs.

## Data flow

```
paste prompt → map to (family, params)
   → python -m evolab.publish <asset> --family … --params … --seed
       → build_run_payload → POST /api/runs/ingest → Browse row (immediate)
       → store.seed_genome → genome enters EvoLab population
   → daemon evolves it
       → new champion → daemon build_run_payload → POST ingest → Browse row (evolved)
```

## Error handling

- Publish POST failures (API down, timeout) are caught in both the daemon and
  the CLI: logged, non-fatal. The daemon keeps searching.
- `published.json` read/write tolerates a missing/corrupt file (treat as empty).
- The ingest endpoint validates the payload minimally and returns the normal
  `save_run` errors; it never runs untrusted code (it persists a pre-computed
  payload, it does not execute strategy code).

## Testing

- `build_run_payload`: shape + metric correctness against a known synthetic
  trades list; `strategy`/`symbol`/`provider` tagging; significance fields present.
- Ingest endpoint: roundtrip on a temp DuckDB (`BACKTEST_LAB_DB` override) →
  row retrievable via `list_runs`/`get_run`.
- `store.seed_genome`: genome inserted, pop cap respected, exact dup dropped,
  atomic write.
- Daemon hook: a `new_champion` result triggers exactly one publish; a repeat
  cycle with the same champion is deduped (no second publish).

## Out of scope (flagged)

- If a pasted prompt needs a signal family not among the 7 in
  `bracket_signals.SIGNALS`, adding that family (+ its genome schema) is a
  separate per-prompt change (still Claude's lane), not part of this infra.
- Enriching the Browse **detail** view with a full equity curve / price bars for
  EvoLab rows — v1 publishes metrics + significance + trades; curve enrichment
  can follow if wanted.
- UI changes to label or filter `evolab:*` rows in the Browse table (chart lane
  is soft-locked).
