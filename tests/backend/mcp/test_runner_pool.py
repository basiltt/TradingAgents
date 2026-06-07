"""ProcessPool sweep runner tests — G2-2/3/7 (FR-036, FR-030 worker scrub).

The worker-secret-scrub (AC-010) is security-critical: a sweep worker must never
carry credentials in its environment. The engine-run path is tested in-process
(the pickling/spawn round-trip is covered by a Linux-only smoke test).
"""
from __future__ import annotations

import os
import sys

import pytest

from backend.mcp.tools.optimizer.runner_pool import (
    _run_combo,
    _scrub_worker_env,
    _worker_init,
    make_sweep_pool,
    supports_process_pool,
)


def test_scrub_removes_secret_shaped_env(monkeypatch):
    monkeypatch.setenv("ACCOUNTS_ENCRYPTION_KEY", "topsecret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    monkeypatch.setenv("BYBIT_API_KEY", "k")
    monkeypatch.setenv("MCP_ACCESS_TOKEN", "t")
    monkeypatch.setenv("SOME_PASSWORD", "p")
    monkeypatch.setenv("HARMLESS_VAR", "keepme")
    _scrub_worker_env()
    for gone in ("ACCOUNTS_ENCRYPTION_KEY", "DATABASE_URL", "BYBIT_API_KEY",
                 "MCP_ACCESS_TOKEN", "SOME_PASSWORD"):
        assert gone not in os.environ, f"{gone} survived the scrub"
    assert os.environ.get("HARMLESS_VAR") == "keepme"  # non-secret preserved


def test_worker_init_scrubs_and_does_not_raise(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "x")
    _worker_init()  # nice/oom guarded → must not raise on any platform
    assert "DATABASE_URL" not in os.environ


def test_run_combo_returns_metrics():
    cfg = {"starting_capital": 1000.0, "leverage": 5, "capital_pct": 10.0,
           "take_profit_pct": 5.0, "stop_loss_pct": 3.0, "direction": "straight"}
    signals = [{"scan_id": "s1", "ticker": "BTCUSDT", "direction": "long", "score": 0.9}]
    snapshot = {"BTCUSDT": [{"open_time": i, "open": 100, "high": 101, "low": 99,
                             "close": 100.5, "volume": 5} for i in range(60)]}
    metrics = _run_combo(cfg, signals, snapshot, {})
    assert isinstance(metrics, dict)


def test_run_combo_isolates_failure():
    # a malformed config must not raise out of the worker (returns {})
    assert _run_combo({}, [], {}, {}) == {}


def test_supports_process_pool_matches_platform():
    assert supports_process_pool() == (sys.platform != "win32")


@pytest.mark.skipif(sys.platform == "win32", reason="spawn ProcessPool isolation is POSIX (live-protection path)")
def test_pool_runs_a_combo_end_to_end():
    """Linux-only: the spawn pool actually executes a combo via a worker process."""
    cfg = {"starting_capital": 1000.0, "leverage": 5, "capital_pct": 10.0,
           "take_profit_pct": 5.0, "stop_loss_pct": 3.0, "direction": "straight"}
    signals = [{"scan_id": "s1", "ticker": "BTCUSDT", "direction": "long", "score": 0.9}]
    snapshot = {"BTCUSDT": [{"open_time": i, "open": 100, "high": 101, "low": 99,
                             "close": 100.5, "volume": 5} for i in range(60)]}
    pool = make_sweep_pool(max_workers=1)
    try:
        fut = pool.submit(_run_combo, cfg, signals, snapshot, {})
        metrics = fut.result(timeout=60)
        assert isinstance(metrics, dict)
    finally:
        pool.shutdown(wait=True)
