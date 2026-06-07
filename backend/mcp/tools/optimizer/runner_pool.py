"""ProcessPool sweep runner — G2-2/3 (FR-036, §15.1/15.12).

Sweep CPU work (each combo's BacktestEngine.run) is offloaded to a separate
ProcessPoolExecutor with the 'spawn' start method so the live event loop is never
CPU-starved by a large fan-out. Each worker:
  - scrubs secrets from os.environ at init (ACCOUNTS_ENCRYPTION_KEY / DATABASE_URL
    / MCP token / *_API_KEY*) — a worker must never carry credentials (FR-030),
  - lowers its scheduling priority (os.nice) + OOM-kill preference
    (oom_score_adj) on POSIX, no-op on Windows,
  - is DB-LESS: it returns a metrics dict; the PARENT persists (no asyncpg in a
    worker).

On Windows (no fork, limited shm semantics) and whenever the pool can't start,
the caller falls back to the in-process orchestrator — same pure engine, just on
the event loop. The live-order-p95 protection that depends on real isolation is
asserted only on Linux (skip-marked elsewhere).
"""
from __future__ import annotations

import os
import sys
from concurrent.futures import ProcessPoolExecutor
from typing import Any

# Env var name substrings that must be removed from a worker's environment.
_SECRET_ENV_MARKERS = (
    "ACCOUNTS_ENCRYPTION_KEY",
    "DATABASE_URL",
    "MCP_TOKEN",
    "MCP_ACCESS_TOKEN",
    "_API_KEY",
    "_API_SECRET",
    "BYBIT_API",
    "SECRET",
    "PASSWORD",
)


def _scrub_worker_env() -> None:
    """Remove credential-shaped variables from this worker's os.environ."""
    for key in list(os.environ.keys()):
        up = key.upper()
        if any(m in up for m in _SECRET_ENV_MARKERS):
            os.environ.pop(key, None)


def _worker_init() -> None:
    """ProcessPool initializer: scrub secrets + de-prioritize the worker."""
    _scrub_worker_env()
    # POSIX-only niceness + OOM preference; guarded so Windows is a clean no-op.
    if sys.platform != "win32":
        try:
            os.nice(10)
        except Exception:  # noqa: BLE001
            pass
        try:
            with open(f"/proc/{os.getpid()}/oom_score_adj", "w") as fh:
                fh.write("500")
        except Exception:  # noqa: BLE001
            pass


def _run_combo(
    config: dict[str, Any],
    signals: list[dict[str, Any]],
    snapshot: dict[str, list[dict[str, Any]]],
    instrument_info: dict[str, Any],
    deadline: float | None = None,
) -> dict[str, Any]:
    """Module-level SYNC worker entrypoint (picklable for spawn). Runs ONE config
    through the engine and returns its metrics dict. DB-less; never raises out —
    a failed combo returns {} so the sweep keeps going. `deadline` (monotonic
    seconds) bounds the run via the engine's cooperative cancel event so a
    pathological config cannot peg a worker forever."""
    import threading
    import time

    cancel_event = threading.Event()
    timer: threading.Timer | None = None
    if deadline is not None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {}
        timer = threading.Timer(remaining, cancel_event.set)
        timer.daemon = True
        timer.start()
    try:
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        result = engine.run(config, signals, snapshot or {}, cancel_event, None, instrument_info or {})
        return dict(result.metrics or {})
    except Exception:  # noqa: BLE001 — isolate combo failures (incl. BacktestCancelled)
        return {}
    finally:
        if timer is not None:
            timer.cancel()


def supports_process_pool() -> bool:
    """True when a spawn ProcessPool is usable (POSIX). Windows → in-process."""
    return sys.platform != "win32"


def make_sweep_pool(max_workers: int | None = None) -> ProcessPoolExecutor:
    """Create a spawn-context ProcessPoolExecutor with the secret-scrubbing
    initializer and ≤ cores-1 workers. Caller owns the lifecycle."""
    import multiprocessing as mp

    cores = os.cpu_count() or 2
    workers = max(1, min(cores - 1, max_workers or cores - 1))
    ctx = mp.get_context("spawn")
    return ProcessPoolExecutor(
        max_workers=workers, mp_context=ctx, initializer=_worker_init
    )
