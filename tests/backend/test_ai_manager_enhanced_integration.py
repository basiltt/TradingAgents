# tests/backend/test_ai_manager_enhanced_integration.py
"""End-to-end test: full pipeline with all enhanced capabilities."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services.ai_manager_graph import build_decision_graph


@pytest.mark.asyncio
async def test_full_pipeline_with_enhanced_data():
    """Graph runs with all enhanced state fields populated."""
    graph = build_decision_graph().compile()

    mock_llm = AsyncMock(return_value='{"action": "HOLD", "symbol": "BTCUSDT", "confidence": 0.6, "reason": "trend aligned"}')

    state = {
        "account_id": "test",
        "config": {"risk_tolerance": "moderate", "locked_positions": []},
        "ws_snapshot": {"positions": [{"symbol": "BTCUSDT", "side": "Buy", "unrealisedPnl": "100"}]},
        "market_data": {"BTCUSDT": {"rsi_14": 55, "ema_trend_strength": 0.01}},
        "peak_pnl": {},
        "daily_realized_pnl": 0.0,
        "daily_profit_target": None,
        "_llm_callable": mock_llm,
        "episodic_memory": [],
        "patterns": [],
        "decision_count": 100,
        # Enhanced fields
        "mtf": {"trend_alignment": 0.7, "dominant_trend": "bullish", "trend_strength": 0.6, "key_levels": [], "divergences": [], "per_tf": {}},
        "orderbook": {"bid_clusters": [], "ask_clusters": [], "imbalance_ratio": 1.2, "spread_bps": 1.0, "depth_ratio": 0.9, "spoofing_flags": []},
        "correlation": {"matrix": {}, "portfolio_heat": 0.2, "clusters": [], "max_correlated_exposure_pct": 0.0},
        "sweep": None,
        "_sweep_blocked_symbols": [],
    }

    result = await graph.ainvoke(state)
    assert result["action"] == "HOLD"
    assert "regime" in result
    assert result.get("_risk_rejected") is not True


@pytest.mark.asyncio
async def test_sweep_block_prevents_close():
    """Sweep block in state prevents FULL_CLOSE."""
    graph = build_decision_graph().compile()

    mock_llm = AsyncMock(return_value='{"action": "FULL_CLOSE", "symbol": "BTCUSDT", "confidence": 0.9, "reason": "exit signal"}')

    state = {
        "account_id": "test",
        "config": {"risk_tolerance": "moderate", "locked_positions": []},
        "ws_snapshot": {"positions": [{"symbol": "BTCUSDT", "side": "Buy", "unrealisedPnl": "-200"}]},
        "market_data": {},
        "peak_pnl": {},
        "daily_realized_pnl": 0.0,
        "daily_profit_target": None,
        "_llm_callable": mock_llm,
        "episodic_memory": [],
        "patterns": [],
        "decision_count": 100,
        "mtf": None,
        "orderbook": None,
        "correlation": None,
        "sweep": {"confidence": 0.85, "direction": "long_hunt"},
        "_sweep_blocked_symbols": ["BTCUSDT"],
    }

    result = await graph.ainvoke(state)
    assert result["action"] == "HOLD"
    assert "sweep" in result.get("reason", "")
