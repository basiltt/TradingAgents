"""Shared test fixtures for backend tests — TASK-001."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _reset_rate_gate_state():
    """Isolate process-wide rate-gate state between tests.

    The Bybit rate gate is a process-wide singleton; a test that exhausts 10006
    retries legitimately trips the ban breaker, which would otherwise leak into
    later tests. Also reset the post-scan revert flags to their default (active)
    state so one test's revert cannot bleed into another.
    """
    try:
        from backend.services.bybit_rate_gate import get_rate_gate
        get_rate_gate().clear_ban()
    except Exception:
        pass
    try:
        from backend.services import post_scan_flags
        post_scan_flags.reset_for_tests()
    except Exception:
        pass
    yield
    try:
        from backend.services.bybit_rate_gate import get_rate_gate
        get_rate_gate().clear_ban()
    except Exception:
        pass

