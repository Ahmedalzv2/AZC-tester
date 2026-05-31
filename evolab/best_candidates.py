"""Daily best-15 candidate publisher.

EvoLab promotes ~zero champions (the fee-wall keeps net edges below the deflated
t-bar), so the search is invisible. This surfaces the strongest *candidates* the
daemon has evolved — ranked by the honest out-of-sample Newey-West t-stat — and
ships them to the gallant showcase clearly marked as candidates, NOT champions.

Honesty is the whole point: every published run carries its real verdict
(noise/marginal/real) and `significant=false` unless it actually cleared the
gate, so gallant's existing red "LOW CONFIDENCE" rendering separates them from a
blessed champion. This is reporting only — it never executes a strategy or
places an order. Anti-Trader.dev by construction.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evolab import data, fitness, publish
from evolab.daemon import resolve_assets, _publish_key
from evolab.genome import Genome
from evolab.search import STATE_DIR
from evolab.store import Store, genome_from_dict

HISTORY_PATH = STATE_DIR / "candidates-history.jsonl"
DEFAULT_TOP_N = 15
DEFAULT_URL = os.environ.get(
    "EVOLAB_PUBLISH_URL", "https://backtest-gallant.srv1688368.hstgr.cloud"
)


@dataclass
class Candidate:
    asset: str
    genome: Genome
    oos_t: float
    oos_n: int
    oos_mean: float
    oos_p: float
    # True only if this genome clears the DEFLATED (multiple-testing) champion
    # bar — i.e. it would actually be promoted. For a best-of-665k-trials pick,
    # the single-hypothesis `assess` verdict over-claims; this is the honest one.
    deflated_significant: bool = False
    deflated_t_bar: float = 0.0
    rank: int = 0  # filled after the global sort

    def as_record(self, batch_date: str) -> dict[str, Any]:
        return {
            "batch_date": batch_date,
            "rank": self.rank,
            "asset": self.asset,
            "family": self.genome.family,
            "params": dict(self.genome.params),
            "oos_t": round(self.oos_t, 4),
            "oos_n": self.oos_n,
            "oos_mean": round(self.oos_mean, 6),
            "oos_p": round(self.oos_p, 6),
            "deflated_significant": self.deflated_significant,
            "deflated_t_bar": round(self.deflated_t_bar, 3),
        }


def _genome_key(g: Genome) -> tuple:
    return (g.family, tuple(sorted(g.params.items())))


def prior_candidate_ids(url: str = DEFAULT_URL) -> list[str]:
    """Run-ids of previously-published candidates on the showcase: an `evolab:`
    strategy that is NOT significant. A real champion (significant=true) is never
    matched, so daily replace preserves champions and only sweeps stale candidates."""
    req = urllib.request.Request(url.rstrip("/") + "/api/runs?limit=200", method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        runs = json.loads(resp.read().decode()).get("runs", [])
    return [r["id"] for r in runs
            if str(r.get("strategy", "")).startswith("evolab:")
            and not r.get("significant", False) and r.get("id")]


def _delete_run(run_id: str, url: str, api_key: str | None) -> None:
    req = urllib.request.Request(url.rstrip("/") + f"/api/runs/{run_id}", method="DELETE")
    if api_key:
        req.add_header("X-API-Key", api_key)
    with urllib.request.urlopen(req, timeout=30):
        pass


def build_leaderboard(assets: list[str] | None = None,
                      top_n: int = DEFAULT_TOP_N) -> list[Candidate]:
    """Pure ranking, no network. Score every (deduped) genome in each asset's
    current population on its OOS holdout, drop thin samples, return the global
    top-N by OOS t-stat. The deflated alpha is passed to evaluate for reporting
    parity with the daemon but does NOT filter the candidate list — these are
    explicitly the best *non*-champions."""
    assets = assets if assets is not None else resolve_assets()
    store = Store(STATE_DIR)
    alpha = store.alpha_deflated()
    deflated_bar = fitness._critical_t(alpha)  # the real champion bar (~5.25 at 665k trials)
    pooled: list[Candidate] = []

    for asset in assets:
        population = store.load_state(asset).get("population", [])
        if not population:
            continue
        try:
            splits = data.split(data.load_asset(asset))
        except Exception:
            continue  # missing fixture -> skip asset, never abort the batch
        seen: set[tuple] = set()
        for gd in population:
            g = genome_from_dict(gd)
            key = _genome_key(g)
            if key in seen:
                continue
            seen.add(key)
            r = fitness.evaluate(g, splits, alpha)
            if r.oos_n < fitness.MIN_OOS_TRADES:
                continue
            pooled.append(Candidate(
                asset, r.genome, r.oos_t, r.oos_n, r.oos_mean, r.oos_p,
                deflated_significant=bool(r.oos_mean > 0 and r.oos_t >= deflated_bar),
                deflated_t_bar=deflated_bar))

    pooled.sort(key=lambda c: c.oos_t, reverse=True)
    board = pooled[:top_n]
    for i, c in enumerate(board, start=1):
        c.rank = i
    return board


def publish_leaderboard(board: list[Candidate], *, batch_date: str,
                        url: str = DEFAULT_URL, dry_run: bool = False,
                        api_key: str | None = None, replace: bool = True) -> list[str]:
    """Ship each candidate to gallant's /api/runs/ingest tagged run_type=candidate,
    and append the batch to the dated history log. With replace=True the previous
    candidate batch is captured first and deleted AFTER the new one posts (no empty
    window, champions untouched). dry_run prints and posts nothing."""
    if api_key is None and not dry_run:
        api_key = _publish_key()  # same env/gallant-.env resolution the daemon uses
    # Capture (don't yet delete) the prior batch so today's posts first.
    stale_ids = prior_candidate_ids(url) if (replace and not dry_run) else []
    run_ids: list[str] = []
    for c in board:
        request_payload, response_payload = publish.build_run_payload(c.asset, c.genome)
        request_payload["run_type"] = "candidate"
        request_payload["rank"] = c.rank
        request_payload["batch_date"] = batch_date
        # Honesty override: `build_run_payload` runs the single-hypothesis
        # `assess`, which over-claims for a genome cherry-picked from a 665k-trial
        # search. A candidate is "significant" only if it clears the DEFLATED
        # champion bar — which by construction it does not (else the daemon would
        # have promoted it). Force the flag the gallant UI keys off so every
        # candidate renders honestly as low-confidence, never a blessed champion.
        sig = response_payload["significance"]
        sig["significant"] = c.deflated_significant
        sig["deflated_t_bar"] = round(c.deflated_t_bar, 3)
        sig["scope"] = "oos (multiple-testing deflated)"
        sig["note"] = ("best-of-search CANDIDATE, not a champion; significant=true "
                       "only if oos_t clears the deflated bar")
        if dry_run:
            print(f"  #{c.rank:<2} {c.asset:<5} {c.genome.family:<16} "
                  f"oos_t={c.oos_t:6.3f} n={c.oos_n:<4} "
                  f"deflated_significant={c.deflated_significant} "
                  f"(bar t>={c.deflated_t_bar:.2f})")
            run_ids.append("")
            continue
        run_ids.append(publish.post_ingest(request_payload, response_payload,
                                           base_url=url, api_key=api_key))

    # Now sweep the prior batch — today's is already live, so no empty window.
    for rid in stale_ids:
        try:
            _delete_run(rid, url, api_key)
        except Exception:
            pass  # a stale row that won't delete is cosmetic, never fail the batch

    if not dry_run and board:
        _append_history(board, batch_date)
    return run_ids


def _append_history(board: list[Candidate], batch_date: str) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_PATH.open("a") as f:
        for c in board:
            f.write(json.dumps(c.as_record(batch_date)) + "\n")


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="evolab.best_candidates",
        description="Publish the top-N evolved genomes (by OOS t) to the gallant showcase.")
    ap.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    ap.add_argument("--url", default=DEFAULT_URL, help="gallant base URL")
    ap.add_argument("--assets", default="", help="comma list to scope (default: full basket)")
    ap.add_argument("--batch-date", default="", help="YYYY-MM-DD stamp (default: today UTC)")
    ap.add_argument("--dry-run", action="store_true", help="print the board, post nothing")
    args = ap.parse_args(argv)

    assets = [a.strip().upper() for a in args.assets.split(",") if a.strip()] or None
    batch_date = args.batch_date.strip()
    if not batch_date:
        # imported lazily so the module stays import-time pure for tests
        from datetime import datetime, timezone
        batch_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    board = build_leaderboard(assets=assets, top_n=args.top_n)
    if not board:
        print("[best15] no candidates with >= "
              f"{fitness.MIN_OOS_TRADES} OOS trades; nothing to publish")
        return 0

    print(f"[best15] top {len(board)} by OOS t (batch {batch_date}) -> "
          f"{'DRY RUN' if args.dry_run else args.url}")
    run_ids = publish_leaderboard(board, batch_date=batch_date, url=args.url,
                                  dry_run=args.dry_run)
    if not args.dry_run:
        print(f"[best15] published {sum(1 for r in run_ids if r)} runs; "
              f"history -> {HISTORY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
