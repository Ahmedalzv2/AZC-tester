# EvoLab Phase 2 — Daemon + Dashboard

**Date:** 2026-05-30
**Status:** Design — approved pending user spec review
**Author:** Claude Code (with Ahmed)

## Goal

Make EvoLab continuous and visible: a gentle always-on daemon that evolves
strategies per asset around the clock, and a standalone `/evolab` dashboard page
that shows the current per-asset champions — or the honest "no champion" null —
with the deflated α and cumulative trial count front and centre (anti-Trader.dev).

Builds on Phase 1 (`evolab/` package, [[evolab-phase1]]). Phases 3 (LLM
proposer) and 4 (shadow forward-test promotion) remain deferred to their own
specs.

## Hard constraints (shape the whole design)

- **Shared tree, locked files.** `static/app.js`, `static/index.html`,
  `static/styles.css` are Hermes's soft-locked Chart.js migration; `app.py`
  carries uncommitted jobs/lifespan work. The design must NOT edit the locked
  static files and must keep the `app.py` edit to a single uncommitted line.
- **`bracket_signals.py` is untracked.** Anything that imports the `evolab`
  package can only run locally, not on origin. The web API therefore must NOT
  import `evolab` — it reads state files directly.
- **Tiny box.** 2 vCPU / ~4 GB. The daemon must be gentle: nice'd, one asset at
  a time, sleep between visits.

## Architecture

```
evolab/daemon.py        # NEW: gentle round-robin search loop (imports evolab; local-only)
evolab/store.py         # EXISTING (mine): add atomic writes + resume guard
evolab_api.py           # NEW: FastAPI APIRouter; reads state files, NO evolab import (pushable)
static/evolab.html      # NEW: standalone page (no overlap with chart layer)
static/evolab.js        # NEW: fetch /api/evolab, render table, poll
static/evolab.css       # NEW: page styles
deploy/evolab-daemon.service  # NEW: systemd unit (nice -n 15)
app.py                  # ONE uncommitted line: app.include_router(evolab_router)
```

Two cleanly separated halves:
- **Producer (local-only):** `evolab/daemon.py` → writes `evolab/state/*.json`.
- **Consumer (pushable):** `evolab_api.py` + `static/evolab.*` → reads those
  files. No code path links the web app to `bracket_signals.py`.

## Components

### evolab/daemon.py (NEW, committed; runs locally)

A long-running loop:
- Assets = `data.available_assets()` (DOGE/SOL/XRP), round-robin.
- Per visit: `run_search(asset, bars, generations=GENS_PER_VISIT, pop_size=POP,
  seed=cycle_index, store=Store(STATE_DIR), ts=<wall-clock ms>)`. Population
  resumes from state, so each visit continues that asset's evolution.
- Bars loaded once per asset and cached in-process (avoids re-parsing the
  fixture every visit).
- Sleep `SLEEP_SECONDS` between visits.
- Per-asset `try/except`: a failing asset is logged and skipped, never kills the
  loop.
- Writes a heartbeat `evolab/state/daemon.json`
  (`{"last_cycle_ts", "cycle", "last_asset", "pid"}`) each visit.
- Config via env with the chosen defaults: `EVOLAB_GENS_PER_VISIT=3`,
  `EVOLAB_SLEEP_SECONDS=30`, `EVOLAB_POP=24`. Parsed once at startup.
- Clean shutdown on SIGTERM (systemd stop): finish the current visit, write a
  final heartbeat, exit 0.
- Logs one line per visit to stdout (journald captures it).

### evolab/store.py (EXISTING — mine; harden)

- **Atomic writes:** `save_state` and `bump_trials` write to a temp file in the
  same dir then `os.replace` onto the target, so a concurrent reader
  (`/api/evolab`) never sees a half-written JSON. (`os.replace` is atomic on the
  same filesystem.)
- **Resume guard:** add `valid_genome(d) -> bool` to `evolab/genome.py` (checks
  the dict has a known family and every schema param present and in-bounds). The
  daemon filters loaded-state genomes through it when rebuilding a population, so
  a manually corrupted/legacy `<asset>.json` can't crash `mutate` with an
  empty-params `KeyError` (the Phase 1 review's noted edge). The store stays a
  pure persistence layer; validation lives in `genome.py` next to the schemas.

### evolab_api.py (NEW, committed; pushable — no evolab import)

`router = APIRouter()`:
- `GET /api/evolab` → reads `EVOLAB_STATE_DIR` (default `evolab/state/`):
  `trials.json` (cumulative + derived `alpha_deflated = 0.05/max(1,cumulative)`),
  each `<asset>.json` (generation, champion, asset), `daemon.json` (heartbeat),
  and the last N lines of `runs.jsonl` for per-asset `best_is_score`/last ts.
  Returns a single JSON object; missing files degrade gracefully to nulls/empties.
  Pure stdlib json + file reads — **never imports `evolab`**.
- `GET /evolab` → `FileResponse(static/evolab.html)`.
- A module-level constant points at the state dir so tests can redirect it.

### static/evolab.html + evolab.js + evolab.css (NEW, committed)

- Minimal self-contained page; no shared CSS/JS with the chart dashboard.
- `evolab.js` fetches `/api/evolab` on load and polls every ~15 s.
- Renders: a header strip (cumulative trials, current deflated α, daemon status
  = "running (last cycle Ns ago)" / "stale" / "stopped"), then a per-asset table:
  asset, generation, best-IS, **champion** (family + params + OOS t / OOS p) or
  a muted "no champion — honest null", last-updated.
- Honesty framing in the header copy: the deflated α and trial count are the
  headline, with a one-line note that champions are hypotheses pending the
  Phase-4 forward test.

### deploy/evolab-daemon.service (NEW, committed) + installed

```
[Unit]
Description=EvoLab strategy-search daemon
After=network.target

[Service]
Type=simple
WorkingDirectory=/root/apps/backtest-lab
ExecStart=/usr/bin/nice -n 15 /root/apps/backtest-lab/.venv/bin/python -m evolab.daemon
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Installed to `/etc/systemd/system/`, `daemon-reload`, `enable --now`.

### app.py (ONE line, left UNCOMMITTED)

`from evolab_api import router as evolab_router` + `app.include_router(evolab_router)`.
NOT committed (app.py is a shared dirty file). Flagged in
`.agent-coordination.md` so whoever commits app.py next includes it. Endpoint
goes live after `docker compose restart backtest-lab` (stateless; safe).

## Data flow

daemon → `run_search` → `Store` (atomic write) → `evolab/state/*.json`
→ `/api/evolab` (file read) → `evolab.js` poll → table render.

No shared mutable state between producer and consumer except the JSON files;
atomic writes make the hand-off safe without locks.

## Error handling

- Daemon: per-asset try/except (log + skip); SIGTERM → graceful finish; on a
  fatal error systemd restarts it (`Restart=on-failure`).
- API: every file read is guarded; missing/corrupt file → that field is null,
  endpoint still returns 200 with whatever is available (a half-built state
  must never 500 the dashboard).
- Store: atomic write means a crash mid-write leaves the previous good file
  intact (temp file is discarded).

## Testing

- `tests/test_evolab_daemon.py`: a bounded helper (e.g. `run_cycles(n=2,
  gens=1, ...)` or the loop body extracted as `one_cycle(...)`) advances state
  and writes a heartbeat; a deliberately broken asset is skipped without
  aborting; NEVER an unbounded loop in a test.
- `tests/test_evolab_api.py`: build a temp state dir with crafted
  `trials.json` + `<asset>.json` + `daemon.json` + `runs.jsonl`, point the API's
  state-dir constant at it, call the route handler directly (the repo's API
  tests don't use a TestClient — no httpx in venv), assert the JSON shape +
  graceful degradation when files are missing.
- `tests/test_evolab_store.py` (extend): atomic write leaves no temp files
  behind and a reader sees either old or new content, never partial; resume
  guard drops a schema-invalid genome.
- Full `tests/test_evolab_*.py` stays green.

## Shared-tree handling (commit plan)

- **Committed (path-scoped, new files):** `evolab/daemon.py`,
  `evolab_api.py`, `static/evolab.html`, `static/evolab.js`, `static/evolab.css`,
  `deploy/evolab-daemon.service`, the `tests/test_evolab_*` additions, and the
  `store.py` hardening (my file).
- **NOT committed:** the one-line `app.py` `include_router` wiring — left in the
  working tree, flagged in `.agent-coordination.md`.
- **Never touched:** `static/app.js`, `static/index.html`, `static/styles.css`
  (Hermes's chart lock).
- Every commit path-scoped; never `git add -A`.

## Non-goals (deferred)

- No link from the main dashboard to `/evolab` yet (would edit locked
  `index.html`); add once Hermes's chart work lands.
- No LLM proposer (Phase 3). No shadow forward-test promotion / "in shadow
  since" column (Phase 4). No multi-process/parallel daemon (single-process is
  enough and avoids file-locking).
- No auth on `/api/evolab` (read-only, same posture as the rest of the lab).

## Open questions

None blocking. `GENS_PER_VISIT`/`SLEEP_SECONDS`/`POP` are env-tunable so cadence
can be adjusted live without code changes.
