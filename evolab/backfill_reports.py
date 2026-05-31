"""One-shot: re-render existing ingested gallant runs so each carries a full
`metrics.report` + dollar-shaped trades. Old EvoLab candidates were stored with a
report-less metrics block and R-native trades, so they opened to an empty Strategy
Report. This rebuilds each run's `response` from its own genome (same fixture =
identical scored result) and overwrites the file in place, preserving id/created_at.
The daily cron regenerates everything correctly going forward; this fixes what is
already on disk. Idempotent: re-running yields the same output.

Usage: python -m evolab.backfill_reports /root/apps/backtest-lab-gallant/runs
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from evolab import universe
from evolab.genome import Genome


def _genome_from(record: dict) -> tuple[str, str, Genome]:
    req = record.get("request", {})
    resp = record.get("response", {})
    evo = resp.get("evolab", {})
    family = evo.get("family") or str(req.get("strategy", "")).removeprefix("evolab:")
    params = evo.get("params") or req.get("strategy_params") or {}
    uni_name = evo.get("universe") or req.get("universe") or "crypto"
    symbol = req.get("symbol") or (resp.get("source", {}) or {}).get("symbol")
    return uni_name, symbol, Genome(family=family, params=dict(params))


def backfill_file(path: Path) -> str:
    record = json.loads(path.read_text())
    if (record.get("response", {}).get("metrics", {}) or {}).get("report"):
        return "skip (already has report)"
    uni_name, symbol, genome = _genome_from(record)
    if not symbol:
        return "skip (no symbol)"
    uni = universe.get(uni_name)
    _req, new_resp = uni.build_payload(symbol, genome)
    # Keep the candidate's original request metadata (rank/batch_date/etc); only the
    # response was deficient. Preserve id + created_at so the run keeps its identity.
    record["response"] = new_resp
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record))
    tmp.replace(path)
    rep = new_resp["metrics"]["report"]
    return f"ok ({uni_name}/{symbol}: {rep['total_trades']} trades, net ${rep['net_pnl']})"


def main(argv: list[str]) -> int:
    runs_dir = Path(argv[1]) if len(argv) > 1 else Path("runs")
    files = sorted(p for p in runs_dir.glob("*.json") if p.name != "index.json")
    ok = 0
    for p in files:
        try:
            result = backfill_file(p)
        except Exception as exc:  # never abort the batch on one bad file
            result = f"ERROR {type(exc).__name__}: {exc}"
        print(f"{p.name}: {result}")
        ok += result.startswith("ok")
    print(f"\nbackfilled {ok}/{len(files)} runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
