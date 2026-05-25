"""AI Manager Decision Graph — Phase 3 Task 3.1.

LangGraph StateGraph compiled ONCE at service startup.
Nodes: preflight → data_aggregation → signal_detection → context_enrichment
       → action_generation → risk_validation → output
Error fallback catches any node failure → HOLD.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from typing import Any, Dict, Optional

from langgraph.graph import END, StateGraph

from backend.services.ai_manager_evaluator import AIManagerEvaluator
from backend.services.ai_manager_prompts import (
    build_context_prompt,
    build_system_prompt,
    sanitize_for_injection,
    sanitize_llm_output,
    validate_regime,
    validate_market_session,
)

logger = logging.getLogger(__name__)

# Valid actions the LLM can return
_VALID_ACTIONS = frozenset(["HOLD", "FULL_CLOSE", "PARTIAL_CLOSE"])

# Cold-start threshold
_COLD_START_DECISION_COUNT = 10
_COLD_START_CONFIDENCE_THRESHOLD = 0.85


def build_decision_graph() -> StateGraph:
    """Build the LangGraph decision graph. Compile once at startup."""
    graph = StateGraph(dict)

    graph.add_node("preflight", preflight_node)
    graph.add_node("data_aggregation", data_aggregation_node)
    graph.add_node("signal_detection", signal_detection_node)
    graph.add_node("context_enrichment", context_enrichment_node)
    graph.add_node("action_generation", action_generation_node)
    graph.add_node("risk_validation", risk_validation_node)
    graph.add_node("output", output_node)
    graph.add_node("error_fallback", error_fallback_node)

    graph.set_entry_point("preflight")

    graph.add_conditional_edges(
        "preflight",
        _route_after_preflight,
        {"continue": "data_aggregation", "reject": "output"},
    )
    graph.add_edge("data_aggregation", "signal_detection")
    graph.add_edge("signal_detection", "context_enrichment")
    graph.add_edge("context_enrichment", "action_generation")
    graph.add_conditional_edges(
        "action_generation",
        _route_after_action,
        {"validate": "risk_validation", "hold": "output", "error": "error_fallback"},
    )
    graph.add_conditional_edges(
        "risk_validation",
        _route_after_risk,
        {"pass": "output", "reject": "output"},
    )
    graph.add_edge("error_fallback", "output")
    graph.add_edge("output", END)

    return graph


def _route_after_preflight(state: Dict[str, Any]) -> str:
    if state.get("_rejected"):
        return "reject"
    return "continue"


def _route_after_action(state: Dict[str, Any]) -> str:
    if state.get("_error"):
        return "error"
    action = state.get("action", "HOLD")
    if action == "HOLD":
        return "hold"
    return "validate"


def _route_after_risk(state: Dict[str, Any]) -> str:
    if state.get("_risk_rejected"):
        return "reject"
    return "pass"


# --- Node implementations ---


async def preflight_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Check positions exist and detect cold-start. Circuit breaker/budget/kill checked by caller."""
    config = state.get("config", {})
    positions = (state.get("ws_snapshot", {}).get("positions")) or []

    if not positions:
        state["_rejected"] = True
        state["action"] = "HOLD"
        state["reason"] = "no_open_positions"
        return state

    # Cold-start detection
    decision_count = state.get("decision_count", 100)
    state["_cold_start"] = decision_count < _COLD_START_DECISION_COUNT

    state["_rejected"] = False
    state["graph_path"] = "preflight"
    return state


async def data_aggregation_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Aggregate position, wallet, and indicator data."""
    ws_snapshot = state.get("ws_snapshot", {})
    state["positions"] = ws_snapshot.get("positions") or []
    state["wallet"] = {
        k: v for k, v in ws_snapshot.items()
        if k in ("equity", "margin", "available_balance", "wallet")
    }
    state["indicators"] = state.get("market_data", {})
    state["graph_path"] = "preflight→data_aggregation"
    return state


async def signal_detection_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Classify urgency based on market signals."""
    evaluator = state.get("_evaluator") or AIManagerEvaluator()
    positions = state.get("positions", [])
    indicators = state.get("indicators", {})
    urgency = evaluator.classify_urgency(positions, indicators)
    state["urgency"] = urgency
    state["graph_path"] = "preflight→data_aggregation→signal_detection"

    # Cold-start restriction: no DEEP evaluations
    if state.get("_cold_start") and urgency == "DEEP":
        state["urgency"] = "STANDARD"

    return state


async def context_enrichment_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Enrich context for STANDARD/DEEP evaluations. Skip for FAST. 20s timeout."""
    urgency = state.get("urgency", "STANDARD")
    state["graph_path"] = "preflight→data_aggregation→signal_detection→context_enrichment"

    if urgency == "FAST":
        state["regime"] = "ranging"
        state["session"] = "unknown"
        state["episodic_memory"] = state.get("episodic_memory", [])
        state["patterns"] = state.get("patterns", [])
        return state

    # For STANDARD/DEEP, attempt enrichment with 20s timeout
    try:
        enrichment = await asyncio.wait_for(
            _do_enrichment(state),
            timeout=20.0,
        )
        state.update(enrichment)
    except asyncio.TimeoutError:
        logger.warning("Context enrichment timed out for %s", state.get("account_id"))
        state["regime"] = "unavailable"
        state["session"] = "unknown"
        state["episodic_memory"] = state.get("episodic_memory", [])
        state["patterns"] = state.get("patterns", [])

    return state


async def _do_enrichment(state: Dict[str, Any]) -> Dict[str, Any]:
    """Perform actual enrichment (memory, patterns, regime)."""
    return {
        "regime": validate_regime(state.get("_raw_regime", "ranging")),
        "session": validate_market_session(state.get("_raw_session", "unknown")),
        "episodic_memory": state.get("episodic_memory", []),
        "patterns": state.get("patterns", []),
    }


async def action_generation_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """LLM call to generate action decision."""
    state["graph_path"] = (
        "preflight→data_aggregation→signal_detection→context_enrichment→action_generation"
    )

    config = state.get("config", {})
    risk_tolerance = config.get("risk_tolerance", "moderate")
    cold_start = state.get("_cold_start", False)

    system_prompt = build_system_prompt(
        risk_tolerance=risk_tolerance,
        cold_start=cold_start,
    )
    context_prompt = build_context_prompt(
        positions=state.get("positions", []),
        wallet=state.get("wallet", {}),
        indicators=state.get("indicators"),
        episodic_memory=state.get("episodic_memory"),
        patterns=state.get("patterns"),
        regime=state.get("regime", "ranging"),
        session=state.get("session", "unknown"),
    )

    # LLM call (injected via state for testability)
    llm_callable = state.get("_llm_callable")
    if not llm_callable:
        state["action"] = "HOLD"
        state["reason"] = "no_llm_configured"
        state["confidence"] = 0.0
        return state

    # Try up to 2 times (retry once on malformed)
    for attempt in range(2):
        try:
            raw_response = await asyncio.wait_for(
                llm_callable(system_prompt, context_prompt),
                timeout=30.0,
            )
            parsed = _parse_llm_response(raw_response)
            if parsed:
                state.update(parsed)
                state["reason"] = sanitize_llm_output(state.get("reason", ""))
                return state
        except asyncio.TimeoutError:
            logger.warning("LLM timeout attempt %d for %s", attempt + 1, state.get("account_id"))
        except Exception:
            logger.exception("LLM call failed attempt %d for %s", attempt + 1, state.get("account_id"))

    # Both attempts failed or malformed → HOLD
    state["action"] = "HOLD"
    state["reason"] = "llm_malformed_or_timeout"
    state["confidence"] = 0.0
    return state


def _parse_llm_response(raw: str) -> Optional[Dict[str, Any]]:
    """Parse structured JSON response from LLM."""
    if not raw:
        return None
    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None

    action = data.get("action", "")
    if action not in _VALID_ACTIONS:
        return None

    symbol = sanitize_for_injection(str(data.get("symbol", "")))
    confidence = float(data.get("confidence", 0.0))
    reason = str(data.get("reason", ""))[:2000]

    if not math.isfinite(confidence):
        confidence = 0.0

    if action != "HOLD" and not symbol:
        return None

    return {
        "action": action,
        "symbol": symbol,
        "confidence": max(0.0, min(1.0, confidence)),
        "reason": reason,
    }


async def risk_validation_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Validate action against risk constraints."""
    state["graph_path"] = (
        "preflight→data_aggregation→signal_detection→context_enrichment"
        "→action_generation→risk_validation"
    )

    config = state.get("config", {})
    symbol = state.get("symbol", "")
    action = state.get("action", "HOLD")

    # Locked positions filter
    locked = config.get("locked_positions", [])
    if symbol in locked:
        state["_risk_rejected"] = True
        state["action"] = "HOLD"
        state["reason"] = f"position_locked: {symbol}"
        return state

    # Symbol validation: must be in current positions
    positions = state.get("positions", [])
    position_symbols = {p.get("symbol", "") for p in positions}
    if symbol and symbol not in position_symbols:
        state["_risk_rejected"] = True
        state["action"] = "HOLD"
        state["reason"] = f"symbol_not_in_positions: {symbol}"
        return state

    # Cold-start confidence threshold
    if state.get("_cold_start"):
        confidence = state.get("confidence", 0.0)
        if confidence < _COLD_START_CONFIDENCE_THRESHOLD:
            state["_risk_rejected"] = True
            state["action"] = "HOLD"
            state["reason"] = "cold_start_confidence_too_low"
            return state

    state["_risk_rejected"] = False
    return state


async def output_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Emit final action result."""
    if "action" not in state:
        state["action"] = "HOLD"
    if "reason" not in state:
        state["reason"] = "default_hold"
    if "confidence" not in state:
        state["confidence"] = 0.0
    if "graph_path" not in state:
        state["graph_path"] = "output"
    return state


async def error_fallback_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Any node failure → HOLD."""
    state["action"] = "HOLD"
    state["reason"] = state.get("_error_reason", "node_failure")
    state["confidence"] = 0.0
    state["graph_path"] = (state.get("graph_path", "") + "→error_fallback")
    return state
