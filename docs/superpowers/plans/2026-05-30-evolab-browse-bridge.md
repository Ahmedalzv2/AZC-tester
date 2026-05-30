# EvoLab → Browse bridge + per-prompt runner — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface EvoLab's validated champions (and operator-pasted strategies) in the tester's Browse dashboard, and seed pasted strategies into EvoLab's search.

**Architecture:** A pure payload-builder in EvoLab's lane (`evolab/publish.py`) runs a genome through EvoLab's own `bracket_signals.simulate_signal` (the exact code that scores champions) and assembles a Browse-shaped `(request, response)` pair. The DB write is routed through the API process via a new auth-guarded `POST /api/runs/ingest` so DuckDB stays single-writer (the daemon is a separate host process). The daemon publishes champions on promotion (deduped); a CLI does immediate-run + seed for pasted prompts.

**Tech Stack:** Python 3, FastAPI, DuckDB, numpy, pandas. Tests via pytest (TestClient for the endpoint).

**Soft-lock (do not edit):** `engine_bracket.py`, `static/*`. Only `bracket_metrics` is *imported* from `engine_bracket` (read-only use, no edit). All new code lives in `evolab/`, plus one endpoint in `app.py`.

---

## File Structure

- **Create** `evolab/publish.py` — payload builder + HTTP POST helper + CLI (`python -m evolab.publish`).
- **Modify** `evolab/store.py` — add `seed_genome(asset, genome)`.
- **Modify** `evolab/daemon.py` — publish champions on `new_champion` (env-gated, deduped).
- **Modify** `app.py` — add `POST /api/runs/ingest`.
- **Create** `tests/test_evolab_publish.py`, `tests/test_evolab_seed.py`, `tests/test_runs_ingest.py`, `tests/test_evolab_daemon_publish.py`.

Interfaces this plan builds against (verified to exist):
- `evolab.data.load_asset(asset) -> list[Bar]`, `evolab.data.make_splits(bars) -> (is_bars, oos_bars)`, `evolab.data.TAKER = 0.00075`.
- `bracket_signals.SIGNALS: dict[str, fn]`, `bracket_signals.simulate_signal(bars, fn, params) -> list[{"ts","dir","netR","win"}]`.
- `evolab.genome.Genome(family: str, params: dict)`, `evolab.genome.FIXED_PARAMS: dict[str, dict]`.
- `evolab.store.genome_to_dict(g)`, `evolab.store.genome_from_dict(d)`, `evolab.store.write_json_atomic(path, obj)`, `Store.load_state(asset)`, `Store.save_state(asset, state)`, `Store.base` (Path).
- `engine_bracket.bracket_metrics(trades) -> {"n","winPct","netR","totalR","maxDD"}` (reads only `t["netR"]`, `t["win"]`).
- `stats.newey_west_tstat(arr, lags)`, `stats.bootstrap_pvalue(arr, seed)`, `stats._default_lags(n)`.
- `storage.save_run(run_type, request_payload, response_payload) -> run_id`, `storage.list_runs(limit)`, `storage.get_run(run_id)`; DB path overridable via env `BACKTEST_LAB_DB`.
- `app.py`: `require_api_key` dependency, `save_run` already imported from `storage`.

---

## Task 0: Install pytest into the venv (one-time prep)

**Files:** none (environment only)

- [ ] **Step 1: Install pytest**

Run: `cd /root/apps/backtest-lab && .venv/bin/pip install pytest`
Expected: `Successfully installed pytest-...`

- [ ] **Step 2: Verify**

Run: `.venv/bin/python -m pytest --version`
Expected: prints a pytest version (no "No module named pytest").

No commit (environment change only).

---

## Task 1: `store.seed_genome` — inject a genome into an asset's population

**Files:**
- Modify: `evolab/store.py`
- Test: `tests/test_evolab_seed.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_evolab_seed.py
from evolab.store import Store, genome_to_dict
from evolab.genome import Genome


def test_seed_prepends_and_dedupes(tmp_path):
    store = Store(tmp_path)
    store.save_state("SOL", {"asset": "SOL", "generation": 5,
                             "population": [genome_to_dict(Genome("ma_cross", {"fast": 10, "slow": 50}))],
                             "champion": None})
    g = Genome("rsi_reversion", {"rsi_n": 14, "lower": 30, "upper": 70})

    store.seed_genome("SOL", g)
    pop = store.load_state("SOL")["population"]
    assert pop[0] == genome_to_dict(g)          # prepended at front
    assert len(pop) == 2                          # original kept

    store.seed_genome("SOL", g)                   # exact duplicate
    pop2 = store.load_state("SOL")["population"]
    assert len(pop2) == 2                          # not added twice


def test_seed_creates_state_when_absent(tmp_path):
    store = Store(tmp_path)
    g = Genome("donchian_break", {"don": 30})
    store.seed_genome("XRP", g)
    state = store.load_state("XRP")
    assert state["population"][0] == genome_to_dict(g)
    assert state["asset"] == "XRP"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/apps/backtest-lab && .venv/bin/python -m pytest tests/test_evolab_seed.py -v`
Expected: FAIL — `AttributeError: 'Store' object has no attribute 'seed_genome'`

- [ ] **Step 3: Implement `seed_genome`**

Add to `evolab/store.py` inside the `Store` class (after `save_state`):

```python
    def seed_genome(self, asset: str, genome: "Genome") -> None:
        """Insert a genome at the front of an asset's population so the daemon
        evolves it on the next visit. Exact-duplicate genomes are dropped; a
        missing state file is created. Atomic write (no torn reads for the
        dashboard)."""
        from evolab.store import genome_to_dict  # local import: module-level fn
        state = self.load_state(asset)
        gd = genome_to_dict(genome)
        pop = state.get("population", [])
        if gd not in pop:
            pop.insert(0, gd)
        state["asset"] = asset
        state["population"] = pop
        state.setdefault("generation", int(state.get("generation", 0)))
        state.setdefault("champion", state.get("champion"))
        self.save_state(asset, state)
```

(Note: `load_state` already returns a sane default dict for a missing file — confirm it returns at least `{}`; if it returns `{}` the `.get` calls above handle it.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_evolab_seed.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add evolab/store.py tests/test_evolab_seed.py
git commit -m "feat(evolab): store.seed_genome injects a genome into a population"
```

---

## Task 2: `publish._assemble_payload` — pure genome → Browse payload

**Files:**
- Create: `evolab/publish.py`
- Test: `tests/test_evolab_publish.py`

This is the pure, IO-free core: given the genome plus the trades and OOS net-R it was scored on, build the `(request_payload, response_payload)` that `save_run` expects. Browse reads `response_payload["metrics"]` and `response_payload["significance"]` for `run_type="backtest"` (verified in `storage._pick_preview`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_evolab_publish.py
from evolab.genome import Genome
from evolab.publish import _assemble_payload


def test_assemble_payload_shape_and_tags():
    g = Genome("rsi_reversion", {"rsi_n": 14, "lower": 30, "upper": 70})
    # 4 trades, 3 wins; netR sums to +1.0
    trades = [
        {"ts": 1, "dir": "long", "netR": 0.5, "win": True},
        {"ts": 2, "dir": "long", "netR": 0.5, "win": True},
        {"ts": 3, "dir": "long", "netR": 0.5, "win": True},
        {"ts": 4, "dir": "long", "netR": -0.5, "win": False},
    ]
    oos_rs = [0.5, -0.5, 0.5, 0.5]
    req, resp = _assemble_payload("SOL", g, trades, oos_rs, is_score=1.23)

    assert req["strategy"] == "evolab:rsi_reversion"
    assert req["data_provider"] == "azc_fixture"
    assert req["symbol"] == "SOL"
    assert req["interval"] == "4h"
    assert req["strategy_params"] == g.params

    m = resp["metrics"]
    assert m["trade_count"] == 4
    assert m["win_rate_pct"] == 75.0
    assert m["total_r"] == 2  # +0.5*3 -0.5
    assert "total_return_pct" in m and "max_drawdown_pct" in m and "sharpe" in m

    s = resp["significance"]
    assert set(["tstat", "pvalue", "significant", "n", "scope"]) <= set(s)
    assert s["scope"] == "oos"
    assert s["n"] == 4
    assert resp["evolab"]["is_score"] == 1.23
    assert resp["evolab"]["family"] == "rsi_reversion"


def test_assemble_payload_empty_trades_is_safe():
    g = Genome("ma_cross", {"fast": 10, "slow": 50})
    req, resp = _assemble_payload("XRP", g, [], [], is_score=float("-inf"))
    assert resp["metrics"]["trade_count"] == 0
    assert resp["significance"]["significant"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_evolab_publish.py::test_assemble_payload_shape_and_tags -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'evolab.publish'`

- [ ] **Step 3: Implement `_assemble_payload` (and helpers) in `evolab/publish.py`**

```python
"""Publish an EvoLab genome's backtest into the tester's Browse run-store.

The DB write is NOT done here (DuckDB is single-writer and the daemon is a
separate process): _assemble_payload builds the payload, post_ingest() ships it
to the API's POST /api/runs/ingest, which owns the DB. build_run_payload runs
the genome through EvoLab's own simulator so Browse shows exactly what EvoLab
scored.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np

from bracket_signals import SIGNALS, simulate_signal
from engine_bracket import bracket_metrics
from evolab import data
from evolab.genome import FIXED_PARAMS, Genome
from stats import _default_lags, bootstrap_pvalue, newey_west_tstat

INTERVAL = "4h"                  # EvoLab fixtures are 4h bars
DEFAULT_RISK_PCT = 0.005         # account risk per trade (matches FIXED_PARAMS default)
P_SEED = 12345                   # deterministic bootstrap (matches fitness.P_SEED intent)


def _significance(net_rs: list[float], scope: str) -> dict[str, Any]:
    arr = np.asarray(net_rs, dtype=float)
    if arr.size < 2:
        return {"tstat": 0.0, "pvalue": 1.0, "significant": False, "n": int(arr.size), "scope": scope}
    t = float(newey_west_tstat(arr, lags=_default_lags(arr.size)))
    p = float(bootstrap_pvalue(arr, seed=P_SEED))
    return {"tstat": t, "pvalue": p, "significant": bool(abs(t) >= 2 and p < 0.05),
            "n": int(arr.size), "scope": scope}


def _assemble_payload(asset: str, genome: Genome, trades: list[dict[str, Any]],
                      oos_rs: list[float], is_score: float) -> tuple[dict[str, Any], dict[str, Any]]:
    bm = bracket_metrics(trades)  # {"n","winPct","netR","totalR","maxDD"} in R units
    risk_pct = float(genome.params.get("riskPct", DEFAULT_RISK_PCT))
    net_rs = [t["netR"] for t in trades]
    arr = np.asarray(net_rs, dtype=float)
    sharpe = float(arr.mean() / (arr.std() + 1e-9)) if arr.size else 0.0

    metrics = {
        "trade_count": bm["n"],
        "win_rate_pct": round(bm["winPct"], 3),
        "total_r": bm["totalR"],
        "avg_r": bm["netR"],
        "max_dd_r": bm["maxDD"],
        # account-level views (R scaled by per-trade risk), clearly derived:
        "total_return_pct": round(bm["totalR"] * risk_pct * 100, 3),
        "max_drawdown_pct": round(-bm["maxDD"] * risk_pct * 100, 3),
        "sharpe": round(sharpe, 3),
        "strategy": f"evolab:{genome.family}",
        "interval": INTERVAL,
        "fee_bps": round(data.TAKER * 1e4, 2),
    }
    significance = _significance(oos_rs, scope="oos")

    request_payload = {
        "strategy": f"evolab:{genome.family}",
        "data_provider": "azc_fixture",
        "symbol": asset,
        "interval": INTERVAL,
        "years": 0,
        "strategy_params": dict(genome.params),
    }
    response_payload = {
        "metrics": metrics,
        "significance": significance,
        "trades": trades,
        "source": {"provider": "evolab", "note": "EvoLab genome via simulate_signal (all-taker)"},
        "evolab": {
            "family": genome.family,
            "params": dict(genome.params),
            "is_score": is_score,
        },
    }
    return request_payload, response_payload
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_evolab_publish.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add evolab/publish.py tests/test_evolab_publish.py
git commit -m "feat(evolab): publish._assemble_payload builds Browse payload from a genome"
```

---

## Task 3: `publish.build_run_payload` — run the genome and assemble

**Files:**
- Modify: `evolab/publish.py`
- Test: `tests/test_evolab_publish.py` (add a case)

`build_run_payload` does the IO (load bars, split, simulate) then delegates to `_assemble_payload`. Test it by monkeypatching `data.load_asset` so it needs no fixture and runs fast.

- [ ] **Step 1: Write the failing test (append to tests/test_evolab_publish.py)**

```python
def test_build_run_payload_runs_a_real_family(monkeypatch):
    from engine_bracket import Bar
    import evolab.publish as pub

    # 120 synthetic 4h bars: a clean uptrend so a trend family produces trades.
    bars = []
    px = 100.0
    for i in range(120):
        px *= 1.01 if i % 7 else 0.99
        bars.append(Bar(t=i, o=px, h=px * 1.01, l=px * 0.99, c=px, v=1000.0))
    monkeypatch.setattr(pub.data, "load_asset", lambda asset: bars)
    monkeypatch.setattr(pub.data, "make_splits", lambda b: (b[: int(len(b) * 0.7)], b[int(len(b) * 0.7):]))

    from evolab.genome import Genome
    req, resp = pub.build_run_payload("SOL", Genome("donchian_break", {"don": 20}))
    assert req["symbol"] == "SOL"
    assert req["strategy"] == "evolab:donchian_break"
    assert "trade_count" in resp["metrics"]
    assert resp["significance"]["scope"] == "oos"
```

(`Bar` field names — verify against `engine_bracket.Bar`; the dataclass uses `t,o,h,l,c,v`. If the real constructor differs, adjust the synthetic bar build to match the actual fields.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_evolab_publish.py::test_build_run_payload_runs_a_real_family -v`
Expected: FAIL — `AttributeError: module 'evolab.publish' has no attribute 'build_run_payload'`

- [ ] **Step 3: Implement `build_run_payload` (append to evolab/publish.py)**

```python
def build_run_payload(asset: str, genome: Genome) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load the asset's bars, run the genome through EvoLab's own simulator over
    full history (for metrics) and over the OOS leg (for the significance gate),
    then assemble the Browse payload."""
    bars = data.load_asset(asset)
    is_bars, oos_bars = data.make_splits(bars)
    params = {**genome.params, **FIXED_PARAMS.get(genome.family, {})}
    fn = SIGNALS[genome.family]
    full_trades = simulate_signal(bars, fn, params)
    oos_rs = [t["netR"] for t in simulate_signal(oos_bars, fn, params)]
    is_rs = [t["netR"] for t in simulate_signal(is_bars, fn, params)]
    arr = np.asarray(is_rs, dtype=float)
    is_score = float(arr.mean() * np.sqrt(arr.size) / (arr.std() + 1e-9)) if arr.size else float("-inf")
    return _assemble_payload(asset, genome, full_trades, oos_rs, is_score)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_evolab_publish.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add evolab/publish.py tests/test_evolab_publish.py
git commit -m "feat(evolab): build_run_payload runs a genome via simulate_signal"
```

---

## Task 4: `POST /api/runs/ingest` endpoint

**Files:**
- Modify: `app.py` (add a model near the other `*Request` models, and a route near `/api/runs`)
- Test: `tests/test_runs_ingest.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_runs_ingest.py
import importlib
import os


def test_ingest_persists_and_lists(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKTEST_LAB_DB", str(tmp_path / "t.duckdb"))
    monkeypatch.delenv("AZC_API_KEY", raising=False)  # auth off for the test
    import storage; importlib.reload(storage)
    import app; importlib.reload(app)
    from fastapi.testclient import TestClient

    client = TestClient(app.app)
    payload = {
        "request_payload": {"strategy": "evolab:rsi_reversion", "data_provider": "azc_fixture",
                            "symbol": "SOL", "interval": "4h", "years": 0, "strategy_params": {"rsi_n": 14}},
        "response_payload": {"metrics": {"trade_count": 5, "total_return_pct": 3.2},
                            "significance": {"tstat": 2.4, "pvalue": 0.01, "significant": True}},
    }
    r = client.post("/api/runs/ingest", json=payload)
    assert r.status_code == 200
    run_id = r.json()["run_id"]
    assert run_id

    listed = client.get("/api/runs").json()["runs"]
    assert any(row["id"] == run_id and row["strategy"] == "evolab:rsi_reversion" for row in listed)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_runs_ingest.py -v`
Expected: FAIL — 404 (route not defined) or assertion on `run_id`.

- [ ] **Step 3: Implement the model + route in `app.py`**

Add near the other request models (after `WalkForwardRequest`):

```python
class IngestRequest(BaseModel):
    request_payload: dict[str, Any]
    response_payload: dict[str, Any]
```

Add a route near the existing `/api/runs` GET handlers:

```python
@app.post("/api/runs/ingest", dependencies=[Depends(require_api_key)])
def ingest_run(req: IngestRequest) -> dict[str, Any]:
    # Persists a PRE-COMPUTED run (e.g. an EvoLab champion). It never executes
    # strategy code — it only stores the supplied payload. Keeps the API process
    # the single DuckDB writer.
    run_type = str(req.request_payload.get("run_type") or "backtest")
    run_id = save_run(run_type, req.request_payload, req.response_payload)
    return {"run_id": run_id}
```

(`save_run`, `Depends`, `require_api_key`, `BaseModel`, `Any` are already imported in `app.py` — verify; if `Any` is missing, add `from typing import Any`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_runs_ingest.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_runs_ingest.py
git commit -m "feat(api): POST /api/runs/ingest persists a pre-computed run"
```

---

## Task 5: `publish.post_ingest` + CLI

**Files:**
- Modify: `evolab/publish.py`
- Test: `tests/test_evolab_publish.py` (add CLI/post cases)

- [ ] **Step 1: Write the failing test (append)**

```python
def test_post_ingest_sends_payload(monkeypatch):
    import evolab.publish as pub
    captured = {}

    def fake_urlopen(req, timeout=0):
        import io, json as _j
        captured["url"] = req.full_url
        captured["body"] = _j.loads(req.data.decode())
        captured["key"] = req.headers.get("X-api-key")
        class R(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return R(b'{"run_id": "abc123"}')

    monkeypatch.setattr(pub.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("AZC_API_KEY", "secret")
    rid = pub.post_ingest({"symbol": "SOL"}, {"metrics": {}}, base_url="http://x:3015")
    assert rid == "abc123"
    assert captured["url"].endswith("/api/runs/ingest")
    assert captured["body"]["request_payload"]["symbol"] == "SOL"
    assert captured["key"] == "secret"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_evolab_publish.py::test_post_ingest_sends_payload -v`
Expected: FAIL — `AttributeError: module 'evolab.publish' has no attribute 'post_ingest'`

- [ ] **Step 3: Implement `post_ingest`, `_api_key`, `publish_genome`, and CLI (append to evolab/publish.py)**

```python
DEFAULT_URL = os.environ.get("TESTER_URL", "http://127.0.0.1:3015").rstrip("/")


def _api_key() -> str:
    key = os.environ.get("AZC_API_KEY", "").strip()
    if key:
        return key
    env = Path(__file__).resolve().parent.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.strip().startswith("AZC_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def post_ingest(request_payload: dict[str, Any], response_payload: dict[str, Any],
                base_url: str = DEFAULT_URL) -> str:
    body = json.dumps({"request_payload": request_payload,
                       "response_payload": response_payload}).encode()
    headers = {"Content-Type": "application/json"}
    key = _api_key()
    if key:
        headers["X-API-Key"] = key
    req = urllib.request.Request(base_url + "/api/runs/ingest", data=body,
                                 method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode()).get("run_id", "")


def publish_genome(asset: str, genome: Genome, base_url: str = DEFAULT_URL) -> str:
    request_payload, response_payload = build_run_payload(asset, genome)
    return post_ingest(request_payload, response_payload, base_url=base_url)


def _main(argv: list[str] | None = None) -> int:
    import argparse
    from evolab.search import STATE_DIR
    from evolab.store import Store

    ap = argparse.ArgumentParser(prog="evolab.publish",
                                 description="Run an EvoLab genome, publish it to Browse, optionally seed it.")
    ap.add_argument("asset")
    ap.add_argument("--family", required=True, choices=sorted(SIGNALS.keys()))
    ap.add_argument("--params", default="{}", help="JSON dict of strategy params")
    ap.add_argument("--seed", action="store_true", help="also inject the genome into the asset population")
    ap.add_argument("--no-publish", action="store_true", help="skip the Browse publish (seed only)")
    ap.add_argument("--url", default=DEFAULT_URL)
    args = ap.parse_args(argv)

    genome = Genome(args.family, json.loads(args.params))
    if not args.no_publish:
        run_id = publish_genome(args.asset, genome, base_url=args.url)
        print(f"published run_id={run_id}  -> {args.url}")
    if args.seed:
        Store(STATE_DIR).seed_genome(args.asset, genome)
        print(f"seeded {args.family} into {args.asset} population")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_evolab_publish.py -v`
Expected: PASS (all publish tests green)

- [ ] **Step 5: Commit**

```bash
git add evolab/publish.py tests/test_evolab_publish.py
git commit -m "feat(evolab): post_ingest + publish CLI (immediate-run + seed)"
```

---

## Task 6: Daemon champion-publish hook (env-gated, deduped)

**Files:**
- Modify: `evolab/daemon.py`
- Test: `tests/test_evolab_daemon_publish.py`

Publish only when `result["new_champion"]` is true and the champion signature changed since last publish. Dedup state in `<state_dir>/published.json`. Env flag `EVOLAB_PUBLISH` (default `"1"`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_evolab_daemon_publish.py
import evolab.daemon as d
from evolab.store import Store


def _champ(asset, score):
    return {"asset": asset, "generation": 3, "new_champion": True,
            "champion": {"family": "rsi_reversion",
                         "params": {"rsi_n": 14, "lower": 30, "upper": 70},
                         "is_score": score}}


def test_maybe_publish_champion_publishes_once_then_dedupes(tmp_path, monkeypatch):
    store = Store(tmp_path)
    calls = []
    monkeypatch.setattr(d, "publish_genome", lambda asset, genome, base_url=None: calls.append((asset, genome.family)) or "rid")
    monkeypatch.setenv("EVOLAB_PUBLISH", "1")

    d.maybe_publish_champion(_champ("SOL", 1.5), store)
    d.maybe_publish_champion(_champ("SOL", 1.5), store)   # same champion -> deduped
    assert calls == [("SOL", "rsi_reversion")]

    d.maybe_publish_champion(_champ("SOL", 1.9), store)   # better champion -> publishes
    assert len(calls) == 2


def test_maybe_publish_disabled_by_env(tmp_path, monkeypatch):
    store = Store(tmp_path)
    calls = []
    monkeypatch.setattr(d, "publish_genome", lambda *a, **k: calls.append(1) or "rid")
    monkeypatch.setenv("EVOLAB_PUBLISH", "0")
    d.maybe_publish_champion(_champ("XRP", 2.0), store)
    assert calls == []


def test_maybe_publish_ignores_non_champion(tmp_path, monkeypatch):
    store = Store(tmp_path)
    calls = []
    monkeypatch.setattr(d, "publish_genome", lambda *a, **k: calls.append(1) or "rid")
    monkeypatch.setenv("EVOLAB_PUBLISH", "1")
    d.maybe_publish_champion({"asset": "SOL", "new_champion": False, "champion": None}, store)
    assert calls == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_evolab_daemon_publish.py -v`
Expected: FAIL — `AttributeError: module 'evolab.daemon' has no attribute 'maybe_publish_champion'`

- [ ] **Step 3: Implement the hook in `evolab/daemon.py`**

At the top of `evolab/daemon.py`, add imports:

```python
from evolab.genome import Genome
from evolab.publish import publish_genome
from evolab.store import write_json_atomic
```

Add the helper (module level):

```python
def _champ_signature(champion: dict[str, Any]) -> str:
    params = champion.get("params", {})
    items = ",".join(f"{k}={params[k]}" for k in sorted(params))
    return f"{champion.get('family')}|{items}|{round(float(champion.get('is_score', 0.0)), 5)}"


def maybe_publish_champion(result: dict[str, Any], store: Store) -> None:
    """Publish a freshly-promoted champion to Browse, once per promotion.
    Env-gated (EVOLAB_PUBLISH != '0'); never raises into the search loop."""
    if os.environ.get("EVOLAB_PUBLISH", "1") == "0":
        return
    if not result.get("new_champion"):
        return
    champion = result.get("champion")
    if not champion:
        return
    sig_path = store.base / "published.json"
    try:
        published = {}
        if sig_path.exists():
            published = __import__("json").loads(sig_path.read_text())
        asset = result["asset"]
        sig = _champ_signature(champion)
        if published.get(asset) == sig:
            return  # already published this exact champion
        genome = Genome(champion["family"], champion.get("params", {}))
        publish_genome(asset, genome)
        published[asset] = sig
        write_json_atomic(sig_path, published)
        print(f"[evolab] published champion {asset} {sig}", flush=True)
    except Exception as err:  # publish must never kill the search loop
        print(f"[evolab] publish FAILED for {result.get('asset')}: {err!r}", flush=True)
```

Then call it inside `one_cycle`, right after the existing `advanced.append(asset)` / champion print, within the per-asset try block:

```python
            maybe_publish_champion(result, store)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_evolab_daemon_publish.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the full evolab + new test suite**

Run: `.venv/bin/python -m pytest tests/test_evolab_seed.py tests/test_evolab_publish.py tests/test_runs_ingest.py tests/test_evolab_daemon_publish.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add evolab/daemon.py tests/test_evolab_daemon_publish.py
git commit -m "feat(evolab): daemon publishes champions to Browse on promotion (deduped, env-gated)"
```

---

## Task 7: Live integration smoke + daemon restart

**Files:** none (operational)

- [ ] **Step 1: Restart the API container so the new `/api/runs/ingest` route is live**

Run: `cd /root/apps/backtest-lab && docker compose restart backtest-lab`
Expected: `Container backtest-lab Started`. (Volume-mounted — restart only, no rebuild.)

- [ ] **Step 2: Immediate-run smoke via the CLI (publishes a real EvoLab row to Browse)**

Run: `cd /root/apps/backtest-lab && .venv/bin/python -m evolab.publish SOL --family rsi_reversion --params '{"rsi_n":14,"lower":30,"upper":70}'`
Expected: prints `published run_id=<id>  -> http://127.0.0.1:3015`

- [ ] **Step 3: Confirm it shows in Browse**

Run: `curl -s 'http://127.0.0.1:3015/api/runs?limit=5' | .venv/bin/python -c "import sys,json;[print(r['id'],r['strategy'],r.get('significance',{}).get('tstat')) for r in json.load(sys.stdin)['runs'] if r['strategy'].startswith('evolab:')]"`
Expected: a row with `strategy=evolab:rsi_reversion` and a tstat.

- [ ] **Step 4: Restart the daemon so the champion hook is live**

Run: `systemctl restart evolab-daemon.service && systemctl is-active evolab-daemon.service`
Expected: `active`. (When a champion is next promoted, it auto-publishes; currently champions are null, so this just arms the hook.)

- [ ] **Step 5: Verify daemon boot has no import errors**

Run: `journalctl -u evolab-daemon.service -n 15 --no-pager`
Expected: `[evolab] daemon up: assets=[...]` with no traceback.

No commit (operational verification).

---

## Self-Review

**Spec coverage:**
- Per-prompt immediate run → Task 5 CLI (`publish_genome` + `post_ingest`) + Task 3 (`build_run_payload`). ✓
- Seed into EvoLab → Task 1 (`seed_genome`) wired into CLI `--seed` (Task 5). ✓
- Champion bridge → Task 6 (`maybe_publish_champion` in daemon). ✓
- Champions-only / dedup → Task 6 `published.json` signature. ✓
- DuckDB single-writer via API → Task 4 endpoint; daemon/CLI POST over HTTP (Tasks 5–6). ✓
- `evolab:<family>` tagging, `run_type="backtest"` → Task 2 `_assemble_payload`. ✓
- No edits to `engine_bracket.py` / `static/*` → only `bracket_metrics` imported. ✓
- Error handling (publish never kills loop) → Task 6 try/except + env gate. ✓
- Testing (payload shape, ingest roundtrip, seed, daemon hook) → Tasks 1–6 tests. ✓

**Placeholder scan:** none — every code step is concrete.

**Type/name consistency:** `build_run_payload`, `_assemble_payload`, `post_ingest`, `publish_genome`, `maybe_publish_champion`, `seed_genome`, `_champ_signature` are used consistently across tasks; `IngestRequest{request_payload, response_payload}` matches `post_ingest`'s body and the endpoint. Metric keys (`trade_count`, `win_rate_pct`, `total_return_pct`, `max_drawdown_pct`, `sharpe`, `total_r`) are defined once in Task 2 and asserted in its test.

**Open verification notes for the implementer (cheap, do as you go):**
- Confirm `engine_bracket.Bar` field names (`t,o,h,l,c,v`) before the Task 3 synthetic-bar test; adjust if the dataclass differs.
- Confirm `app.py` already imports `Any` (Task 4) — add `from typing import Any` if not.
- Confirm `Store.load_state` returns a dict for a missing asset (Task 1 relies on `.get`).
