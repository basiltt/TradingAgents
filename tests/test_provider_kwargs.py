"""Tests for _get_provider_kwargs with llm_api_key passthrough."""

from unittest.mock import patch, MagicMock


def test_api_key_passed_to_provider_kwargs():
    with patch("tradingagents.graph.trading_graph.set_config"):
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
        graph.config = {
            "llm_provider": "anthropic",
            "llm_api_key": "sk-test-key",
        }
        kwargs = graph._get_provider_kwargs()
        assert kwargs["api_key"] == "sk-test-key"


def test_no_api_key_when_absent():
    with patch("tradingagents.graph.trading_graph.set_config"):
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
        graph.config = {
            "llm_provider": "anthropic",
        }
        kwargs = graph._get_provider_kwargs()
        assert "api_key" not in kwargs


def test_api_key_with_effort():
    with patch("tradingagents.graph.trading_graph.set_config"):
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
        graph.config = {
            "llm_provider": "anthropic",
            "llm_api_key": "sk-custom",
            "anthropic_effort": "high",
        }
        kwargs = graph._get_provider_kwargs()
        assert kwargs["api_key"] == "sk-custom"
        assert kwargs["effort"] == "high"


def test_api_key_with_openai_provider():
    with patch("tradingagents.graph.trading_graph.set_config"):
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
        graph.config = {
            "llm_provider": "openai",
            "llm_api_key": "sk-openai-key",
            "openai_reasoning_effort": "medium",
        }
        kwargs = graph._get_provider_kwargs()
        assert kwargs["api_key"] == "sk-openai-key"
        assert kwargs["reasoning_effort"] == "medium"
