"""Tests for AI Manager Decision Graph — Phase 3."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.services.ai_manager_graph import (
    build_decision_graph,
    preflight_node,
    data_aggregation_node,
    signal_detection_node,
    risk_validation_node,
    action_generation_node,
    output_node,
    error_fallback_node,
    _parse_llm_response,
)


@pytest.fixture
def base_state():
    return {
        "account_id": "acc-1",
        "config": {"risk_tolerance": "moderate", "locked_positions": []},
        "ws_snapshot": {
            "positions": [{"symbol": "BTCUSDT", "side": "Buy", "size": 0.1, "avgPrice": 50000}],
            "equity": 10000,
            "available_balance": 5000,
        },
        "market_data": {},
        "decision_count": 50,
    }


class TestPreflightNode:
    @pytest.mark.asyncio
    async def test_no_positions_rejects(self):
        state = {"ws_snapshot": {"positions": []}, "config": {}}
        result = await preflight_node(state)
        assert result["_rejected"] is True
        assert result["action"] == "HOLD"

    @pytest.mark.asyncio
    async def test_with_positions_continues(self, base_state):
        result = await preflight_node(base_state)
        assert result["_rejected"] is False

    @pytest.mark.asyncio
    async def test_cold_start_detection(self):
        state = {
            "ws_snapshot": {"positions": [{"symbol": "X"}]},
            "config": {},
            "decision_count": 5,
        }
        result = await preflight_node(state)
        assert result["_cold_start"] is True

    @pytest.mark.asyncio
    async def test_not_cold_start(self, base_state):
        result = await preflight_node(base_state)
        assert result["_cold_start"] is False


class TestDataAggregationNode:
    @pytest.mark.asyncio
    async def test_extracts_positions_and_wallet(self, base_state):
        result = await data_aggregation_node(base_state)
        assert len(result["positions"]) == 1
        assert "equity" in result["wallet"]


class TestSignalDetectionNode:
    @pytest.mark.asyncio
    async def test_standard_by_default(self, base_state):
        base_state["positions"] = base_state["ws_snapshot"]["positions"]
        base_state["indicators"] = {}
        result = await signal_detection_node(base_state)
        assert result["urgency"] == "STANDARD"

    @pytest.mark.asyncio
    async def test_cold_start_blocks_deep(self, base_state):
        base_state["positions"] = base_state["ws_snapshot"]["positions"]
        base_state["indicators"] = {"BTCUSDT": {"conflicting": True}}
        base_state["_cold_start"] = True
        result = await signal_detection_node(base_state)
        assert result["urgency"] == "STANDARD"


class TestActionGenerationNode:
    @pytest.mark.asyncio
    async def test_no_llm_returns_hold(self, base_state):
        base_state["positions"] = [{"symbol": "BTCUSDT"}]
        base_state["wallet"] = {}
        result = await action_generation_node(base_state)
        assert result["action"] == "HOLD"
        assert result["reason"] == "no_llm_configured"

    @pytest.mark.asyncio
    async def test_valid_llm_response_parsed(self, base_state):
        async def mock_llm(system, context):
            return '{"action": "FULL_CLOSE", "symbol": "BTCUSDT", "confidence": 0.9, "reason": "reversal"}'

        base_state["_llm_callable"] = mock_llm
        base_state["positions"] = [{"symbol": "BTCUSDT"}]
        base_state["wallet"] = {}
        result = await action_generation_node(base_state)
        assert result["action"] == "FULL_CLOSE"
        assert result["symbol"] == "BTCUSDT"
        assert result["confidence"] == 0.9

    @pytest.mark.asyncio
    async def test_malformed_twice_returns_hold(self, base_state):
        async def mock_llm(system, context):
            return "not valid json"

        base_state["_llm_callable"] = mock_llm
        base_state["positions"] = [{"symbol": "BTCUSDT"}]
        base_state["wallet"] = {}
        result = await action_generation_node(base_state)
        assert result["action"] == "HOLD"
        assert "malformed" in result["reason"]

    @pytest.mark.asyncio
    async def test_timeout_returns_hold(self, base_state):
        async def mock_llm(system, context):
            await asyncio.sleep(60)

        base_state["_llm_callable"] = mock_llm
        base_state["positions"] = [{"symbol": "BTCUSDT"}]
        base_state["wallet"] = {}
        # Patch timeout to be fast
        import backend.services.ai_manager_graph as graph_mod
        result = await action_generation_node(base_state)
        assert result["action"] == "HOLD"


class TestRiskValidationNode:
    @pytest.mark.asyncio
    async def test_locked_position_rejected(self, base_state):
        base_state["config"]["locked_positions"] = ["BTCUSDT"]
        base_state["symbol"] = "BTCUSDT"
        base_state["action"] = "FULL_CLOSE"
        base_state["positions"] = [{"symbol": "BTCUSDT"}]
        result = await risk_validation_node(base_state)
        assert result["_risk_rejected"] is True
        assert result["action"] == "HOLD"

    @pytest.mark.asyncio
    async def test_symbol_not_in_positions_rejected(self, base_state):
        base_state["symbol"] = "ETHUSDT"
        base_state["action"] = "FULL_CLOSE"
        base_state["positions"] = [{"symbol": "BTCUSDT"}]
        result = await risk_validation_node(base_state)
        assert result["_risk_rejected"] is True
        assert "not_in_positions" in result["reason"]

    @pytest.mark.asyncio
    async def test_cold_start_low_confidence_rejected(self, base_state):
        base_state["_cold_start"] = True
        base_state["symbol"] = "BTCUSDT"
        base_state["action"] = "FULL_CLOSE"
        base_state["confidence"] = 0.7
        base_state["positions"] = [{"symbol": "BTCUSDT"}]
        result = await risk_validation_node(base_state)
        assert result["_risk_rejected"] is True

    @pytest.mark.asyncio
    async def test_valid_action_passes(self, base_state):
        base_state["symbol"] = "BTCUSDT"
        base_state["action"] = "FULL_CLOSE"
        base_state["confidence"] = 0.9
        base_state["positions"] = [{"symbol": "BTCUSDT"}]
        base_state["_cold_start"] = False
        result = await risk_validation_node(base_state)
        assert result.get("_risk_rejected") is False


class TestParseLlmResponse:
    def test_valid_json(self):
        r = _parse_llm_response('{"action":"FULL_CLOSE","symbol":"BTC","confidence":0.8,"reason":"test"}')
        assert r["action"] == "FULL_CLOSE"
        assert r["symbol"] == "BTC"

    def test_invalid_action(self):
        assert _parse_llm_response('{"action":"BUY","symbol":"BTC","confidence":0.8}') is None

    def test_close_without_symbol(self):
        assert _parse_llm_response('{"action":"FULL_CLOSE","symbol":"","confidence":0.8}') is None

    def test_hold_without_symbol_ok(self):
        r = _parse_llm_response('{"action":"HOLD","symbol":"","confidence":0.5,"reason":"no signal"}')
        assert r["action"] == "HOLD"

    def test_malformed_json(self):
        assert _parse_llm_response("not json") is None

    def test_markdown_fenced(self):
        r = _parse_llm_response('```json\n{"action":"HOLD","symbol":"","confidence":0.5,"reason":"ok"}\n```')
        assert r["action"] == "HOLD"

    def test_confidence_clamped(self):
        r = _parse_llm_response('{"action":"HOLD","symbol":"","confidence":1.5,"reason":"x"}')
        assert r["confidence"] == 1.0


class TestErrorFallbackNode:
    @pytest.mark.asyncio
    async def test_returns_hold(self):
        state = {"graph_path": "action_generation", "_error_reason": "crash"}
        result = await error_fallback_node(state)
        assert result["action"] == "HOLD"
        assert "error_fallback" in result["graph_path"]


class TestOutputNode:
    @pytest.mark.asyncio
    async def test_defaults_to_hold(self):
        result = await output_node({})
        assert result["action"] == "HOLD"


class TestGraphCompilation:
    def test_graph_compiles(self):
        graph = build_decision_graph()
        compiled = graph.compile()
        assert compiled is not None

    @pytest.mark.asyncio
    async def test_full_graph_hold_path(self):
        graph = build_decision_graph().compile()
        state = {
            "account_id": "acc-1",
            "config": {},
            "ws_snapshot": {"positions": [{"symbol": "BTCUSDT"}]},
            "market_data": {},
            "decision_count": 50,
        }
        result = await graph.ainvoke(state)
        assert result["action"] == "HOLD"

    @pytest.mark.asyncio
    async def test_full_graph_no_positions(self):
        graph = build_decision_graph().compile()
        state = {
            "account_id": "acc-1",
            "config": {},
            "ws_snapshot": {"positions": []},
            "market_data": {},
        }
        result = await graph.ainvoke(state)
        assert result["action"] == "HOLD"
        assert result["reason"] == "no_open_positions"

    @pytest.mark.asyncio
    async def test_graph_reentrance(self):
        """Two concurrent ainvoke calls must not cross-contaminate."""
        graph = build_decision_graph().compile()

        state_a = {
            "account_id": "acc-A",
            "config": {},
            "ws_snapshot": {"positions": [{"symbol": "BTCUSDT"}]},
            "market_data": {},
            "decision_count": 50,
        }
        state_b = {
            "account_id": "acc-B",
            "config": {},
            "ws_snapshot": {"positions": [{"symbol": "ETHUSDT"}]},
            "market_data": {},
            "decision_count": 50,
        }

        result_a, result_b = await asyncio.gather(
            graph.ainvoke(state_a),
            graph.ainvoke(state_b),
        )
        # Both return HOLD (no LLM configured), but shouldn't share state
        assert result_a["account_id"] == "acc-A"
        assert result_b["account_id"] == "acc-B"


# === context_enrichment_node tests ===


@pytest.mark.asyncio
async def test_context_enrichment_fast_skips():
    from backend.services.ai_manager_graph import context_enrichment_node
    state = {"urgency": "FAST", "episodic_memory": [{"a": 1}], "patterns": []}
    result = await context_enrichment_node(state)
    assert result["regime"] == "ranging"
    assert result["session"] == "unknown"
    assert result["episodic_memory"] == [{"a": 1}]


@pytest.mark.asyncio
async def test_context_enrichment_timeout_defaults():
    from backend.services.ai_manager_graph import context_enrichment_node
    import asyncio
    from unittest.mock import patch

    async def slow_enrichment(state):
        await asyncio.sleep(100)
        return {}

    state = {"urgency": "STANDARD", "account_id": "acc-1"}
    with patch("backend.services.ai_manager_graph._do_enrichment", slow_enrichment):
        with patch("backend.services.ai_manager_graph.asyncio.wait_for", side_effect=asyncio.TimeoutError):
            result = await context_enrichment_node(state)
    assert result["regime"] == "unavailable"
    assert result["session"] == "unknown"


@pytest.mark.asyncio
async def test_risk_validation_blocks_sweep():
    from backend.services.ai_manager_graph import risk_validation_node
    state = {
        "config": {},
        "symbol": "BTCUSDT",
        "action": "FULL_CLOSE",
        "positions": [{"symbol": "BTCUSDT"}],
        "_sweep_blocked_symbols": ["BTCUSDT"],
        "urgency": "STANDARD",
        "confidence": 0.9,
    }
    result = await risk_validation_node(state)
    assert result["_risk_rejected"] is True
    assert result["action"] == "HOLD"
    assert "sweep" in result["reason"]

@pytest.mark.asyncio
async def test_risk_validation_emergency_overrides_sweep():
    from backend.services.ai_manager_graph import risk_validation_node
    state = {
        "config": {},
        "symbol": "BTCUSDT",
        "action": "FULL_CLOSE",
        "positions": [{"symbol": "BTCUSDT"}],
        "_sweep_blocked_symbols": ["BTCUSDT"],
        "urgency": "EMERGENCY",
        "confidence": 0.9,
    }
    result = await risk_validation_node(state)
    assert result["_risk_rejected"] is False

@pytest.mark.asyncio
async def test_data_aggregation_passes_enhanced_data():
    from backend.services.ai_manager_graph import data_aggregation_node
    state = {
        "ws_snapshot": {"positions": [{"symbol": "BTCUSDT"}]},
        "market_data": {"BTCUSDT": {"rsi_14": 55}},
        "mtf": {"trend_alignment": 0.7},
        "orderbook": {"imbalance_ratio": 1.3},
        "correlation": {"portfolio_heat": 0.5},
        "sweep": None,
    }
    result = await data_aggregation_node(state)
    assert result["mtf"] == {"trend_alignment": 0.7}
    assert result["orderbook"] == {"imbalance_ratio": 1.3}
