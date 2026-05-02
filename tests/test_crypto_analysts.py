"""Tests for crypto analyst agent functions (TASK-011)."""

from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, patch, call
from langchain_core.messages import AIMessage


def _mock_llm(content="test response", tool_calls=None):
    msg = AIMessage(content=content, tool_calls=tool_calls or [])
    llm = MagicMock()
    llm.bind_tools.return_value = llm
    llm.invoke.return_value = msg
    bound = MagicMock()
    bound.invoke.return_value = msg
    chain_result = MagicMock()
    chain_result.invoke.return_value = msg
    return llm


def _base_state():
    return {
        "messages": [],
        "company_of_interest": "BTCUSDT",
        "trade_date": "2025-01-15",
        "market_report": "",
        "sentiment_report": "",
        "news_report": "",
        "fundamentals_report": "",
        "investment_plan": "",
        "trader_investment_plan": "",
        "risk_debate_state": {
            "history": "",
            "aggressive_history": "",
            "conservative_history": "",
            "neutral_history": "",
            "latest_speaker": "",
            "current_aggressive_response": "",
            "current_conservative_response": "",
            "current_neutral_response": "",
            "judge_decision": "",
            "count": 0,
        },
        "final_trade_decision": "",
        "past_context": "",
    }


class TestCryptoTechnicalAnalyst:
    def test_returns_market_report_key(self):
        from tradingagents.agents.crypto_analysts import create_crypto_technical_analyst
        from tradingagents.agents.utils.crypto_agent_utils import make_crypto_tools
        tools = make_crypto_tools(cache={})
        result_msg = AIMessage(content="BTC is bullish", tool_calls=[])

        llm = MagicMock()
        llm.bind_tools.return_value = MagicMock(**{"invoke.return_value": result_msg})

        node = create_crypto_technical_analyst(llm, tools)
        state = _base_state()
        # Patch the chain invoke to return our mock message
        with patch("tradingagents.agents.crypto_analysts.ChatPromptTemplate") as mock_tpl:
            mock_chain = MagicMock()
            mock_chain.invoke.return_value = result_msg
            mock_prompt = MagicMock()
            mock_prompt.__or__ = MagicMock(return_value=mock_chain)
            mock_tpl.from_messages.return_value.partial.return_value = mock_prompt
            result = node(state)
            assert "market_report" in result
            assert result["market_report"] == "BTC is bullish"


class TestCryptoNewsAnalyst:
    def test_uses_news_tools(self):
        from tradingagents.agents.crypto_analysts import create_crypto_news_analyst
        llm = MagicMock()
        result_msg = AIMessage(content="News report", tool_calls=[])
        llm.bind_tools.return_value.invoke.return_value = result_msg

        node = create_crypto_news_analyst(llm)
        state = _base_state()
        result = node(state)
        assert "news_report" in result


class TestCryptoDerivativesAnalyst:
    def test_returns_fundamentals_report_key(self):
        from tradingagents.agents.crypto_analysts import create_crypto_derivatives_analyst
        from tradingagents.agents.utils.crypto_agent_utils import make_crypto_tools
        tools = make_crypto_tools(cache={})
        llm = MagicMock()
        result_msg = AIMessage(content="OI is rising", tool_calls=[])
        llm.bind_tools.return_value.invoke.return_value = result_msg

        node = create_crypto_derivatives_analyst(llm, tools)
        state = _base_state()
        result = node(state)
        assert "fundamentals_report" in result


class TestCryptoTrader:
    def test_produces_trader_investment_plan(self):
        from tradingagents.agents.crypto_analysts import create_crypto_trader

        valid_signal = json.dumps({
            "trade_type": "Long",
            "entry_price": 100000,
            "stop_losses": [95000],
            "take_profits": [110000],
            "confidence": 7,
            "leverage": 5,
        })
        llm = MagicMock()
        llm.invoke.return_value = AIMessage(content=f"```json\n{valid_signal}\n```")

        node = create_crypto_trader(llm)
        state = _base_state()
        state["investment_plan"] = "Analysts say buy"
        result = node(state)
        assert "trader_investment_plan" in result
        assert "Long" in result["trader_investment_plan"]

    def test_retry_on_invalid_signal(self):
        from tradingagents.agents.crypto_analysts import create_crypto_trader

        invalid_signal = json.dumps({
            "trade_type": "Long",
            "entry_price": 100000,
            "stop_losses": [105000],  # SL above entry = invalid for Long
            "take_profits": [110000],
            "confidence": 7,
            "leverage": 5,
        })
        valid_signal = json.dumps({
            "trade_type": "Long",
            "entry_price": 100000,
            "stop_losses": [95000],
            "take_profits": [110000],
            "confidence": 7,
            "leverage": 5,
        })

        llm = MagicMock()
        llm.invoke.side_effect = [
            AIMessage(content=f"```json\n{invalid_signal}\n```"),
            AIMessage(content=f"```json\n{valid_signal}\n```"),
        ]

        node = create_crypto_trader(llm)
        state = _base_state()
        state["investment_plan"] = "Analysts say buy"
        result = node(state)
        assert llm.invoke.call_count == 2
        assert "Long" in result["trader_investment_plan"]

    def test_retry_exhausted_returns_error(self):
        from tradingagents.agents.crypto_analysts import create_crypto_trader

        invalid_signal = json.dumps({
            "trade_type": "Long",
            "entry_price": 100000,
            "stop_losses": [105000],
            "take_profits": [110000],
            "confidence": 7,
            "leverage": 5,
        })

        llm = MagicMock()
        llm.invoke.return_value = AIMessage(content=f"```json\n{invalid_signal}\n```")

        node = create_crypto_trader(llm)
        state = _base_state()
        state["investment_plan"] = "Analysts say buy"
        result = node(state)
        assert "error" in result["trader_investment_plan"].lower() or "invalid" in result["trader_investment_plan"].lower()


class TestCryptoRiskDebaters:
    def test_bull_debater_updates_risk_state(self):
        from tradingagents.agents.crypto_analysts import create_crypto_risk_bull_debater
        llm = MagicMock()
        llm.invoke.return_value = AIMessage(content="Bull case: leverage is managed")
        node = create_crypto_risk_bull_debater(llm)
        state = _base_state()
        state["trader_investment_plan"] = "Long BTC 5x"
        result = node(state)
        assert "risk_debate_state" in result
        assert result["risk_debate_state"]["count"] == 1

    def test_bear_debater_updates_risk_state(self):
        from tradingagents.agents.crypto_analysts import create_crypto_risk_bear_debater
        llm = MagicMock()
        llm.invoke.return_value = AIMessage(content="Bear case: liquidation risk")
        node = create_crypto_risk_bear_debater(llm)
        state = _base_state()
        state["trader_investment_plan"] = "Long BTC 5x"
        result = node(state)
        assert "risk_debate_state" in result
        assert result["risk_debate_state"]["count"] == 1


class TestCryptoPortfolioManager:
    def test_returns_final_decision(self):
        from tradingagents.agents.crypto_analysts import create_crypto_portfolio_manager
        llm = MagicMock()
        llm.invoke.return_value = AIMessage(content="Final: Buy BTC with 3x leverage")
        node = create_crypto_portfolio_manager(llm)
        state = _base_state()
        state["investment_plan"] = "Buy BTC"
        state["trader_investment_plan"] = "Long BTC"
        state["risk_debate_state"]["history"] = "Bull: good. Bear: risky."
        result = node(state)
        assert "final_trade_decision" in result
