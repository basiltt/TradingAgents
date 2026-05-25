"""AI Manager Decision Graph — Phase 3 Task 3.1 (stub).

Provides build_decision_graph() so the service can compile at startup.
Full implementation deferred to Phase 3.
"""

from __future__ import annotations

from typing import Any, Dict


class _StubGraph:
    """Minimal stub that satisfies compiled_graph.ainvoke(state_dict)."""

    async def ainvoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        return {"action": "HOLD", "reason": "stub_graph"}

    def compile(self):
        return self


def build_decision_graph() -> _StubGraph:
    return _StubGraph()
