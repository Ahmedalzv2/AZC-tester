# EvoLab Proven-Universe Lane — design

**Date:** 2026-05-31
**Status:** approved (brainstorm), implementing

## Problem

EvoLab evolves crypto 4h perps, where the fee-wall keeps every edge below the
champion bar (best OOS t≈1.3). The best-15 showcase therefore shows only
"least-dead crypto." But the playbook (§1) has a **proven, fundable edge**:
diversified trend-following on equity indices + commodities — Donchian breakout,
ATR stop, chandelier trail — **HAC t=9.07 over ~100y, positive in 21/21 five-year
eras, OOS t=3.16.** EvoLab just isn't pointed at it. Point it there and the
showcase becomes "is the real edge still firing?" instead of crypto noise.

## Decisions (brainstorm)

- **Fee:** 2bp taker (realistic ETF/micro-futures incl. commission+slippage).
- **Deflation:** SEPARATE trial budget — own Store, own cumulative counter, own
  deflated bar. Index candidates are never punished for 665k crypto trials.
- **Scope:** ADD the proven lane; keep crypto evolving (forward control + paper
  lane). Best-15 publishes a proven-tagged board alongside crypto.
- **Universe:** full playbook set — `^GSPC ^IXIC ^DJI ^RUT ^FTSE ^GDAXI ^N225
  GC=F CL=F SI=F HG=F NG=F` (the exact basket that scored t=9), yahoo
  `period='max'` daily.

## Architecture — a `Universe` abstraction

EvoLab's `data.py` hardcodes crypto (fixtures dir, 7.5bps `TAKER`, hourly→4h
resample, single Store at `STATE_DIR`). Rather than entangle that, add a thin
universe layer; crypto keeps its exact current behavior.

### New: `evolab/universe.py`
A `Universe` carrying everything the leaderboard needs, so `build_leaderboard`
becomes universe-agnostic:
- `name` (`crypto` | `proven`), `interval` (`4h` | `1d`)
- `assets() -> list[str]`
- `load_split(asset) -> (is_bars, oos_bars)` — proven loads daily fixtures with
  NO resample; crypto delegates to `data.load_asset`/`data.split`.
- `store -> Store` at the universe's own state dir (`state/` vs `state-proven/`).
- `alpha_deflated() -> float` from that store.
- `score(genome, is_bars, oos_bars) -> ScoreResult{oos_t,oos_n,oos_mean,oos_p}`
  using `bracket_signals.simulate_signal` with the universe's fee merged last.
  (Mirrors `fitness.evaluate`'s OOS scoring but with the universe fee — does NOT
  modify `fitness.py`, which is Hermes-owned. Reuses the stable `fitness._tstat`
  / `_pvalue` / `_critical_t` helpers.)
- `build_payload(asset, genome) -> (request, response)` — proven uses interval
  `1d` + 2bp; crypto delegates to `publish.build_run_payload` unchanged.

`PROVEN_FEE = {makerEntry:False, makerTp:False, takerRate:0.0002, slipBps:0}`.

### New: `scripts/fetch_proven_fixtures.py`
yfinance `period='max'` daily for the 12 symbols → `evolab/fixtures/proven/<SYM>.json`
(OHLC rows). Re-runnable to refresh. (yfinance 1.4.1 verified: ^GSPC = 24,719
daily bars 1927→2026.)

### New: `evolab/seed_proven.py` (v1 fast path)
Seed each proven asset's population with the playbook's KNOWN-GOOD daily-trend
genomes — Donchian {50,75,100} × ATR {2,3} × trail {3,5} × gate {on(erMin .35),
off} — so the board shows the real edge immediately, before any daemon
evolution. Idempotent (dedup against existing population).

### Changed (my files only): `evolab/best_candidates.py`
- `build_leaderboard(universe, top_n)` — takes a `Universe`; everything routes
  through it (assets, load_split, score, alpha_deflated). Crypto path preserved
  via a `crypto` Universe that wraps current behavior (no regression).
- `publish_leaderboard(..., universe)` — payload via `universe.build_payload`,
  request tagged `universe=<name>`; **per-universe replace**: only sweeps prior
  rows whose `universe` matches (proven never deletes crypto rows; champions of
  either universe preserved).
- CLI `--universe crypto|proven` (default crypto). Cron runs both.

### Changed (my file): `evolab/publish.py`
`prior_candidate_ids` / sweep already filters `evolab:`+not-significant; add a
`universe` filter so replace is per-universe. (`post_ingest` change already
shipped.)

## Honesty / significance — unchanged
Same deflated-bar `significant` flag, computed against the proven Store's OWN
trial budget. A genuinely strong trend genome can now clear a meaningful bar
instead of crypto's 5.26. If it clears, it's real — but still only a backtest
hypothesis until forward-validated (the ETF paper lane already does that).

## Hard constraints
Research/reporting only — no execution, no capital. Funding the proven edge is
the broker problem (playbook §6), explicitly out of scope. New files + additive
flags to my own files only; no touch to `fitness.py`/`data.py`/Hermes's set.

## Testing (TDD)
- `universe.score` applies 2bp (not 7.5bps) and uses daily bars without resample.
- proven Store deflation is independent of crypto's counter.
- `build_leaderboard(proven_universe)` ranks seeded genomes by OOS t.
- `build_leaderboard(crypto_universe)` reproduces current crypto behavior (no regression).
- per-universe replace: a proven batch never returns crypto run-ids for deletion.
- fetch script writes well-formed fixtures (smoke, network-gated/skippable).

## Risks handled in-build
- Genome ranges: widen the seed/proven Donchian bound to 100 if `PARAM_SCHEMAS`
  caps lower (verify).
- Trade counts: daily Donchian-50 over ~24k bars clears `oos_n≥40`; confirm per symbol.

## Out of scope (fast-follow)
- Continuous daemon evolution of the proven universe (v1 seeds + scores; the
  daemon refines later).
- A proven-universe live execution / paper lane (broker-dependent).
