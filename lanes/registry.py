"""Rejection registry — the durable, machine-readable strategy graveyard.

When a lane fails its lifecycle test it is retired here, permanently. Every
future study / search / lane is meant to call is_rejected() first and auto-skip
what's already been disproven, so dead ends are never re-litigated. This is
playbook §3 ("WHAT DOESN'T WORK — do not retry") made queryable.

Append-only JSONL; one rejection per line. The file is the memory and is meant
to be committed (not gitignored), seeded with the already-known dead strategies.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

REGISTRY_PATH = Path(__file__).resolve().parent / "rejected-strategies.jsonl"


def signature(kind: str, params: dict[str, Any], venue: str, asset: str) -> str:
    """Stable short id for a strategy's identity. Param dict order is irrelevant
    (keys are sorted), so the same config always hashes the same."""
    payload = json.dumps(
        {"kind": kind, "venue": venue, "asset": asset, "params": params},
        sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(payload.encode()).hexdigest()[:12]


def register_rejection(kind: str, params: dict[str, Any], venue: str, asset: str,
                       *, reason: str, metrics: dict[str, Any], date: str,
                       path: Path = REGISTRY_PATH) -> str:
    """Append a rejection and return its signature. Idempotent at the read layer:
    re-registering the same signature just adds another dated line; is_rejected
    returns the first match."""
    sig = signature(kind, params, venue, asset)
    entry = {"signature": sig, "kind": kind, "venue": venue, "asset": asset,
             "params": params, "reason": reason, "metrics": metrics, "date": date}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return sig


def is_rejected(sig: str, path: Path = REGISTRY_PATH) -> tuple[bool, dict | None]:
    """Has this signature been disproven? Returns (True, entry) or (False, None)."""
    if not path.exists():
        return False, None
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        entry = json.loads(line)
        if entry.get("signature") == sig:
            return True, entry
    return False, None


def list_rejections(path: Path = REGISTRY_PATH) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]
