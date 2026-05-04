"""Tests for tradingagents.graph.trading_graph._get_provider_kwargs — Phase 1 unit tests."""

from unittest.mock import patch, MagicMock
import pytest


class TestGetProviderKwargs:
    def _make_graph_with_config(self, config):
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        # We can't fully instantiate TradingAgentsGraph without LLM setup,
        # so we test _get_provider_kwargs by constructing partially
        obj = object.__new__(TradingAgentsGraph)
        obj.config = config
        return obj

    def test_google_thinking_level(self):
        obj = self._make_graph_with_config({
            "llm_provider": "google",
            "google_thinking_level": "medium",
        })
        result = obj._get_provider_kwargs()
        assert result == {"thinking_level": "medium"}

    def test_google_no_thinking_level(self):
        obj = self._make_graph_with_config({
            "llm_provider": "google",
        })
        result = obj._get_provider_kwargs()
        assert result == {}

    def test_openai_reasoning_effort(self):
        obj = self._make_graph_with_config({
            "llm_provider": "openai",
            "openai_reasoning_effort": "high",
        })
        result = obj._get_provider_kwargs()
        assert result == {"reasoning_effort": "high"}

    def test_anthropic_effort(self):
        obj = self._make_graph_with_config({
            "llm_provider": "anthropic",
            "anthropic_effort": "high",
        })
        result = obj._get_provider_kwargs()
        assert result == {"effort": "high"}

    def test_unknown_provider_empty(self):
        obj = self._make_graph_with_config({
            "llm_provider": "unknown",
        })
        result = obj._get_provider_kwargs()
        assert result == {}
