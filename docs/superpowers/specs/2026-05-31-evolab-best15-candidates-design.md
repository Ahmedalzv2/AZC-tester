# EvoLab Daily Best-15 Candidate Publisher — design

**Date:** 2026-05-31
**Status:** approved (brainstorm), implementing

## Problem

EvoLab's daemon evolves 25 crypto assets continuously (gen 1000+, 665k+ trials)
but promotes **zero** champions — partly the now-fixed unsatisfiable gate
(commit 9c39836), but mostly the documented crypto fee-wall (net edges run
t < 1.2, nothing clears the deflated t≈5.25 champion bar). Result: the user sees
no strategy reports at all. The champions store is empty and stays empty.

The fix is **best-candidate reporting**: surface the strongest evolved genomes
each day even when none are statistically blessed — ranked honestly, labeled
honestly — so the search is observable without lying about significance.

## Goal

Every 24h, publish the **top 15 evolved genomes ranked by out-of-sample
Newey-West t-stat** to the running **gallant showcase** (3016,
`backtest-gallant.srv1688368.hstgr.cloud`), each clearly stamped as a candidate
with its verdict (`noise`/`marginal`/`real`) — never silently presented as a
blessed champion.

## Decisions (from brainstorm)

- **Surface:** gallant (3016). Already has `/api/runs/ingest` + Browse UI. No new deploy.
- **Ranking:** 15 total across all assets, by OOS NW t-stat desc. The honest metric the gate itself uses.
- **Honesty:** two-tier *intent* satisfied by the existing Browse rendering —
  candidates ship `significance.significant=false` + real verdict, so gallant's
  existing red "LOW CONFIDENCE" styling separates them from any green "real"
  champion. A literal two-*section* split needs a `static/app.js` edit (Hermes's
  locked file) → deferred optional follow-up, not v1.
- **Refresh:** source = current evolved population per asset; candidate tier
  replaced daily (recency-ordered on gallant). A day's 15 also appended to a
  dated history log for the longitudinal "is evolution improving?" trend.

## Architecture

New self-contained module `evolab/best_candidates.py`. Touches **no** shared/
locked files (`app.py`, `static/`, `engine*`, `sweep`, `providers/`).

### Flow (`build_leaderboard` → `publish_leaderboard`)

1. For each asset in the basket (`daemon`-style discovery, `EVOLAB_ASSETS`
   override honored): load population from `Store.load_state`, dedup genomes by
   `(family, sorted params)`.
2. Load + split the asset once (`data.load_asset` + `data.split`); score every
   genome via `fitness.evaluate(genome, splits, alpha_deflated)` →
   `FitnessResult`. `alpha_deflated` from `Store.alpha_deflated()` (reporting
   only — does not gate the candidate list).
3. Keep only `oos_n >= fitness.MIN_OOS_TRADES` (t meaningless below 40 trades).
4. Pool all assets; rank by `oos_t` desc; take top 15.
5. For each of the 15: build the honest fee-applied payload via the existing
   `publish.build_run_payload`, then in the request_payload set
   `run_type="candidate"`, `rank`, and `batch_date`; `publish.post_ingest` →
   gallant. Verdict/`significant=false` already carried by `build_run_payload`.
6. Append the 15-row leaderboard (asset, family, params, oos_t, oos_n, oos_mean,
   oos_p, verdict, rank, batch_date) to `evolab/state/candidates-history.jsonl`.

### Interfaces

- `build_leaderboard(assets=None, top_n=15) -> list[Candidate]` — pure ranking,
  no network. Unit-testable with a tiny fixture store.
- `publish_leaderboard(leaderboard, url, dry_run=False) -> list[str]` — side
  effects (HTTP + history append). `--dry-run` prints, posts nothing.
- CLI: `python -m evolab.best_candidates [--top-n 15] [--url <gallant>]
  [--dry-run] [--assets SOL,XRP]`.

### Scheduling

Daily root cron (or systemd timer) →
`cd /root/apps/backtest-lab && .venv/bin/python -m evolab.best_candidates --publish`.
Time: 06:00 UTC (after the daemon has run overnight). Logs to
`/var/log/evolab-best15.log`.

## Hard constraints

- **Research/reporting only.** No live execution, no order placement, no
  capital. Read store → backtest-score → display. Aligns with the stood-down
  live lane (azc-trader stopped 2026-05-30).
- **No dishonest framing.** Every candidate carries its true verdict; the word
  "champion" is reserved for gate-passing genomes. Anti-Trader.dev by design.
- **Shared-tree safe.** New files only; no edit to Hermes's working set.

## Risks to verify during build

1. Gallant must not auto-prune non-significant runs (would delete candidates).
   If it does, `run_type="candidate"` gets an exemption. — verify against
   gallant's store/prune logic.
2. Scoring 25 populations on OOS must be cron-fast (in-memory; expected seconds).
3. `fitness.py` is under concurrent Hermes edit (cross-fold selection score).
   This module depends only on the stable `FitnessResult` fields
   (`oos_t/oos_n/oos_mean/oos_p/genome`), which are unchanged — compatible
   regardless of how `is_score`/`is_mean` selection evolves.

## Out of scope (later)

- Literal two-section Browse UI (needs `static/` + Hermes coord).
- Atomic "delete yesterday's candidates" (needs a gallant delete endpoint).
- Forward/shadow validation of candidates (Phase 4 shadow gate).
