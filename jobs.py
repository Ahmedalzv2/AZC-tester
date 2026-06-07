"""Process-pool offload for CPU-bound backtests.

FastAPI runs sync ``def`` endpoints in a threadpool, so the event loop is never
blocked. But the heavy work (parameter sweeps, bootstrap p-values) is CPU-bound
and Python's GIL serializes it *inside the web process* — one big sweep pegs a
core and starves every other request behind the GIL.

Running that work in a separate process frees the web process's GIL: the
threadpool thread submitting the job just idle-waits on the result pipe (no CPU,
GIL released), so concurrent requests stay responsive. The endpoints still block
for the result, so the request/response contract is unchanged — only the GIL
contention is gone.

This is the "ProcessPoolExecutor first" step: no Redis/Celery broker, no async
job/polling rewrite. Graceful fallback to in-process execution if the pool can't
be spawned (sandboxed envs that forbid fork) or a worker dies mid-job.
"""
from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import Any, Callable

_pool: ProcessPoolExecutor | None = None


def _max_workers() -> int:
    # Leave a core for the event loop / OS. min 1.
    return max(1, (os.cpu_count() or 2) - 1)


def get_pool() -> ProcessPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ProcessPoolExecutor(max_workers=_max_workers())
    return _pool


def _reset_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=False, cancel_futures=True)
    _pool = None


def shutdown() -> None:
    """Tear the pool down (call on app shutdown)."""
    _reset_pool()


def run_in_pool(fn: Callable[..., Any], /, **kwargs: Any) -> Any:
    """Run a picklable compute fn in a worker process and block for its result.

    ``fn`` and every value in ``kwargs`` must be picklable (module-level
    functions, DataFrames, dicts, strings — all fine here). Exceptions raised by
    ``fn`` propagate unchanged so callers' existing try/except still works; only
    pool-level failures trigger the in-process fallback.
    """
    try:
        future = get_pool().submit(fn, **kwargs)
    except (OSError, RuntimeError):
        # Couldn't start/submit to the pool (e.g. fork forbidden). Run inline.
        return fn(**kwargs)
    try:
        return future.result()
    except BrokenProcessPool:
        # A worker died (OOM, segfault in a native lib). Rebuild the pool and
        # serve this request inline so the user still gets an answer.
        _reset_pool()
        return fn(**kwargs)
