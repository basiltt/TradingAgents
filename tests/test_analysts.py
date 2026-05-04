"""Tests for tradingagents.agents.analysts — Phase 1 unit tests."""

from unittest.mock import MagicMock, patch
import pytest


def _make_mock_llm(content="analysis report", tool_calls=None):
    """Create a mock LLM that returns a mock AIMessage."""
    mock_msg = MagicMock()
    mock_msg.content = content
    mock_msg.tool_calls = tool_calls or []

    mock_chain = MagicMock()
    mock_chain.invoke.return_value = mock_msg

    mock_bound = MagicMock()
    mock_bound.__or__ = MagicMock(return_value=mock_chain)

    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value = mock_bound

    # prompt | llm.bind_tools(tools) needs to work via __or__
    # The actual pattern is: prompt_template | bound_llm → chain
    # We mock at chain.invoke level
    return mock_llm, mock_chain


class TestMarketAnalyst:
    @patch("tradingagents.agents.analysts.market_analyst.get_language_instruction", return_value="")
    @patch("tradingagents.agents.analysts.market_analyst.build_instrument_context", return_value="stock ctx")
    def test_returns_report_when_no_tool_calls(self, mock_ctx, mock_lang):
        from tradingagents.agents.analysts.market_analyst import create_market_analyst

        mock_llm, mock_chain = _make_mock_llm(content="Market is bullish", tool_calls=[])
        node = create_market_analyst(mock_llm)

        # We need to patch the chain creation (prompt | llm.bind_tools)
        # Easiest: patch ChatPromptTemplate to return something that pipes to our chain
        with patch("tradingagents.agents.analysts.market_analyst.ChatPromptTemplate") as mock_pt:
            mock_prompt = MagicMock()
            mock_prompt.partial.return_value = mock_prompt
            mock_prompt.__or__ = MagicMock(return_value=mock_chain)
            mock_pt.from_messages.return_value = mock_prompt

            state = {
                "trade_date": "2025-01-10",
                "company_of_interest": "AAPL",
                "messages": [],
            }
            result = node(state)

        assert result["market_report"] == "Market is bullish"
        assert "messages" in result

    @patch("tradingagents.agents.analysts.market_analyst.get_language_instruction", return_value="")
    @patch("tradingagents.agents.analysts.market_analyst.build_instrument_context", return_value="ctx")
    def test_returns_empty_report_when_tool_calls(self, mock_ctx, mock_lang):
        from tradingagents.agents.analysts.market_analyst import create_market_analyst

        mock_llm, mock_chain = _make_mock_llm(content="ignored", tool_calls=[{"name": "get_stock_data"}])
        node = create_market_analyst(mock_llm)

        with patch("tradingagents.agents.analysts.market_analyst.ChatPromptTemplate") as mock_pt:
            mock_prompt = MagicMock()
            mock_prompt.partial.return_value = mock_prompt
            mock_prompt.__or__ = MagicMock(return_value=mock_chain)
            mock_pt.from_messages.return_value = mock_prompt

            state = {
                "trade_date": "2025-01-10",
                "company_of_interest": "AAPL",
                "messages": [],
            }
            result = node(state)

        assert result["market_report"] == ""
