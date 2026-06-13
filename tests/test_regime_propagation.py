"""Phase 2 — regime_context threads into initial graph state (spec FR-3).

The propagator is the contract point: analysis_service passes
regime_context=request.get("regime_context","") into create_initial_state.
"""
from tradingagents.graph.propagation import Propagator


def test_create_initial_state_stores_regime_context():
    p = Propagator()
    state = p.create_initial_state("BTCUSDT", "2026-06-13", regime_context="REGIME-X")
    assert state["regime_context"] == "REGIME-X"


def test_create_initial_state_defaults_regime_context_empty():
    p = Propagator()
    state = p.create_initial_state("BTCUSDT", "2026-06-13")
    assert state["regime_context"] == ""
