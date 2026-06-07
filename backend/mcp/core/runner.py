"""BacktestRunner protocol — TASK-P0/P3 seam.

Trading-free interface the optimizer (P4) depends on. `BacktestService` satisfies
it (P3 adapter) and `FakeBacktestRunner` (tests) implements it. `run_one`
executes ONE config against a pre-loaded klines snapshot and returns a metrics
dict — the in-process baseline path. The ProcessPool worker (P4) uses a separate
module-level sync entrypoint for the same engine.
"""
from __future__ import annotations

from typing import Any, Protocol


class BacktestRunner(Protocol):
    async def run_one(
        self,
        config: dict[str, Any],
        signals: list[dict[str, Any]],
        snapshot: dict[str, list[dict[str, Any]]],
        instrument_info: dict[str, Any],
        *,
        deadline: float | None = None,
    ) -> dict[str, Any]:
        """Run one backtest against a pre-loaded snapshot; return a metrics dict."""
        ...
