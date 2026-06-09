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
        """The analysis/persistence DB handle, or None if unset."""
        return getattr(self._state, "db", None)

    @property
    def backtest_service(self) -> Any:
        """The BacktestService for running/querying backtests, or None if unset."""
        return getattr(self._state, "backtest_service", None)

    @property
    def backtest_runner(self) -> Any:
        """The BacktestRunner for sweeps (set by the optimizer composition)."""
        return getattr(self._state, "mcp_backtest_runner", None)

    @property
    def accounts_service(self) -> Any:
        """The AccountsService for account/balance reads, or None if unset."""
        return getattr(self._state, "accounts_service", None)

    @property
    def scanner_service(self) -> Any:
        """The ScannerService for scan reads/launches, or None if unset."""
        return getattr(self._state, "scanner_service", None)

    @property
    def trade_repo(self) -> Any:
        """TradeRepository for trade/position reads (read-only methods only)."""
        return getattr(self._state, "trade_repo", None)

    @property
    def signal_analytics_service(self) -> Any:
        """The SignalAnalyticsService for signal-quality metrics, or None if unset."""
        return getattr(self._state, "signal_analytics_service", None)

    @property
    def sector_service(self) -> Any:
        """The SectorService for symbol/sector classification, or None if unset."""
        return getattr(self._state, "sector_service", None)

    @property
    def sweep_repo(self) -> Any:
        """SweepRepository for async sweep persistence (lazily built on the pool)."""
        return getattr(self._state, "mcp_sweep_repo", None)

    @property
    def debug_trace_recorder(self) -> Any:
        """The auto-trade debug trace recorder, or None if unset."""
        return getattr(self._state, "debug_trace_recorder", None)
