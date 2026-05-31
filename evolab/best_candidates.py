"""Daily best-15 candidate publisher (multi-universe).

EvoLab promotes ~zero champions (fee-wall / deflation), so the search is
invisible. This surfaces the strongest evolved genomes per universe — ranked by
the honest out-of-sample Newey-West t-stat — on the gallant showcase, clearly
marked as candidates, NOT champions.

Two universes (see evolab/universe.py): `crypto` (4h perps, 7.5bps) and `proven`
(indices+commodities daily, 2bp — the playbook's fundable trend universe). Each
has its own deflation budget; each publishes a separately-replaced board.

Honesty is the whole point: a candidate's `significant` flag is forced to the
DEFLATED bar of ITS universe, so gallant's red "LOW CONFIDENCE" rendering keeps
candidates distinct from any blessed champion. Reporting only — never executes a
strategy or places an order. Anti-Trader.dev by construction.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Any

from evolab import fitness, publish, universe as uni
from evolab.daemon import _publish_key
from evolab.genome import Genome
from evolab.store import genome_from_dict

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
    # True only if this genome clears the DEFLATED champion bar of its universe.
    # A best-of-search pick's single-hypothesis verdict over-claims; this is honest.
    deflated_significant: bool = False
    deflated_t_bar: float = 0.0
    rank: int = 0

    def as_record(self, batch_date: str, universe_name: str) -> dict[str, Any]:
        return {
            "batch_date": batch_date, "universe": universe_name, "rank": self.rank,
            "asset": self.asset, "family": self.genome.family,
            "params": dict(self.genome.params),
            "oos_t": round(self.oos_t, 4), "oos_n": self.oos_n,
            "oos_mean": round(self.oos_mean, 6), "oos_p": round(self.oos_p, 6),
            "deflated_significant": self.deflated_significant,
            "deflated_t_bar": round(self.deflated_t_bar, 3),
        }


def _genome_key(g: Genome) -> tuple:
    return (g.family, tuple(sorted(g.params.items())))


def prior_candidate_ids(url: str = DEFAULT_URL, interval: str | None = None) -> list[str]:
    """Run-ids of previously-published candidates on the showcase: an `evolab:`
    strategy that is NOT significant. Scoped by `interval` so a universe replaces
    only its own rows (crypto=4h, proven=1d) and never the other's — and a real
    champion (significant=true) is never matched."""
    req = urllib.request.Request(url.rstrip("/") + "/api/runs?limit=200", method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        runs = json.loads(resp.read().decode()).get("runs", [])
    return [r["id"] for r in runs
            if str(r.get("strategy", "")).startswith("evolab:")
            and not r.get("significant", False)
            and (interval is None or r.get("interval") == interval)
            and r.get("id")]


def _delete_run(run_id: str, url: str, api_key: str | None) -> None:
    req = urllib.request.Request(url.rstrip("/") + f"/api/runs/{run_id}", method="DELETE")
    if api_key:
        req.add_header("X-API-Key", api_key)
    with urllib.request.urlopen(req, timeout=30):
        pass


def build_leaderboard(universe: uni.Universe, top_n: int = DEFAULT_TOP_N) -> list[Candidate]:
    """Pure ranking, no network. Score every (deduped) genome in each asset's
    population on its OOS holdout via the universe's scorer/fee, drop thin
    samples, return the global top-N by OOS t-stat. The universe's OWN deflated
    alpha decides each candidate's significant flag (reporting only — it does not
    filter the list; these are explicitly the best non-champions)."""
    store = universe.store()
    pooled: list[Candidate] = []
    n_scored = 0  # configs compared this batch == the multiple-testing count

    for asset in universe.assets():
        population = store.load_state(asset).get("population", [])
        if not population:
            continue
        try:
            is_bars, oos_bars = universe.load_split(asset)
        except Exception:
            continue  # missing/bad fixture -> skip asset, never abort the batch
        seen: set[tuple] = set()
        for gd in population:
            g = genome_from_dict(gd)
            key = _genome_key(g)
            if key in seen:
                continue
            seen.add(key)
            r = universe.score(g, is_bars, oos_bars)
            n_scored += 1
            if r.oos_n < fitness.MIN_OOS_TRADES:
                continue
            pooled.append(Candidate(asset, r.genome, r.oos_t, r.oos_n, r.oos_mean, r.oos_p))

    # Honest deflation: the bar reflects BOTH the daemon's lifetime trials AND the
    # configs we just compared to pick these — picking the best of N backtests is a
    # multiple comparison whether the daemon logged it or not. Counting n_scored
    # (a fixed seed grid) is stable day-to-day; re-testing the same hypotheses
    # doesn't keep inflating it.
    effective_trials = max(store.cumulative_trials(), n_scored, 1)
    deflated_bar = fitness._critical_t(0.05 / effective_trials)
    for c in pooled:
        c.deflated_t_bar = deflated_bar
        c.deflated_significant = bool(c.oos_mean > 0 and c.oos_t >= deflated_bar)

    pooled.sort(key=lambda c: c.oos_t, reverse=True)
    board = pooled[:top_n]
    for i, c in enumerate(board, start=1):
        c.rank = i
    return board


def publish_leaderboard(board: list[Candidate], *, batch_date: str, universe: uni.Universe,
                        url: str = DEFAULT_URL, dry_run: bool = False,
                        api_key: str | None = None, replace: bool = True) -> list[str]:
    """Ship each candidate to gallant tagged run_type=candidate + universe, append
    to the universe's dated history log, and (replace=True) sweep the prior batch
    of THIS universe AFTER the new one posts (no empty window, champions + the
    other universe untouched). dry_run prints and posts nothing."""
    if api_key is None and not dry_run:
        api_key = _publish_key()
    stale_ids = (prior_candidate_ids(url, interval=universe.interval)
                 if (replace and not dry_run) else [])
    run_ids: list[str] = []
    for c in board:
        request_payload, response_payload = universe.build_payload(c.asset, c.genome)
        request_payload["run_type"] = "candidate"
        request_payload["rank"] = c.rank
        request_payload["batch_date"] = batch_date
        request_payload["universe"] = universe.name
        # Honesty override: significant only if it clears THIS universe's deflated bar.
        sig = response_payload["significance"]
        sig["significant"] = c.deflated_significant
        sig["deflated_t_bar"] = round(c.deflated_t_bar, 3)
        sig["scope"] = "oos (multiple-testing deflated)"
        sig["note"] = ("best-of-search CANDIDATE, not a champion; significant=true "
                       "only if oos_t clears the deflated bar")
        if dry_run:
            print(f"  #{c.rank:<2} {c.asset:<6} {c.genome.family:<16} "
                  f"oos_t={c.oos_t:6.3f} n={c.oos_n:<5} "
                  f"deflated_significant={c.deflated_significant} (bar t>={c.deflated_t_bar:.2f})")
            run_ids.append("")
            continue
        run_ids.append(publish.post_ingest(request_payload, response_payload,
                                           base_url=url, api_key=api_key))

    for rid in stale_ids:
        try:
            _delete_run(rid, url, api_key)
        except Exception:
            pass  # a stale row that won't delete is cosmetic, never fail the batch

    if not dry_run and board:
        _append_history(board, batch_date, universe)
    return run_ids


def _append_history(board: list[Candidate], batch_date: str, universe: uni.Universe) -> None:
    path = universe.state_dir / "candidates-history.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        for c in board:
            f.write(json.dumps(c.as_record(batch_date, universe.name)) + "\n")


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="evolab.best_candidates",
        description="Publish the top-N evolved genomes (by OOS t) to the gallant showcase.")
    ap.add_argument("--universe", default="crypto", choices=sorted(uni.UNIVERSES))
    ap.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    ap.add_argument("--url", default=DEFAULT_URL, help="gallant base URL")
    ap.add_argument("--batch-date", default="", help="YYYY-MM-DD stamp (default: today UTC)")
    ap.add_argument("--dry-run", action="store_true", help="print the board, post nothing")
    args = ap.parse_args(argv)

    universe = uni.get(args.universe)
    batch_date = args.batch_date.strip()
    if not batch_date:
        from datetime import datetime, timezone
        batch_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    board = build_leaderboard(universe, top_n=args.top_n)
    if not board:
        print(f"[best15:{universe.name}] no candidates with >= "
              f"{fitness.MIN_OOS_TRADES} OOS trades; nothing to publish")
        return 0

    print(f"[best15:{universe.name}] top {len(board)} by OOS t (batch {batch_date}) -> "
          f"{'DRY RUN' if args.dry_run else args.url}")
    run_ids = publish_leaderboard(board, batch_date=batch_date, universe=universe,
                                  url=args.url, dry_run=args.dry_run)
    if not args.dry_run:
        print(f"[best15:{universe.name}] published {sum(1 for r in run_ids if r)} runs; "
              f"history -> {universe.state_dir / 'candidates-history.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
