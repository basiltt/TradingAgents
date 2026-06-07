"""Service accessors — TASK-P0-06.

Handlers receive `ctx.services` (this object), never `app.state` directly. It
lazily resolves the live service singletons from `app.state` at call time so the
MCP package never imports service instances at module load.
"""
from __future__ import annotations

from typing import Any


class ServiceAccessors:
    """Lazy, read-time accessors over app.state for tool handlers."""

    def __init__(self, app_state: Any) -> None:
        self._state = app_state

    @property
    def db(self) -> Any:
        return getattr(self._state, "db", None)

    @property
    def backtest_service(self) -> Any:
        return getattr(self._state, "backtest_service", None)

    @property
    def backtest_runner(self) -> Any:
        """The BacktestRunner for sweeps (set by the optimizer composition)."""
        return getattr(self._state, "mcp_backtest_runner", None)

    @property
    def accounts_service(self) -> Any:
        return getattr(self._state, "accounts_service", None)

    @property
    def scanner_service(self) -> Any:
        return getattr(self._state, "scanner_service", None)

    @property
    def debug_trace_recorder(self) -> Any:
        return getattr(self._state, "debug_trace_recorder", None)
