"""Tests for tradingagents.graph.conditional_logic — Phase 1 unit tests."""

from unittest.mock import MagicMock

from tradingagents.graph.conditional_logic import ConditionalLogic


def _make_state(messages=None, debate_state=None, risk_state=None):
    state = {}
    if messages is not None:
        state["messages"] = messages
    if debate_state is not None:
        state["investment_debate_state"] = debate_state
    if risk_state is not None:
        state["risk_debate_state"] = risk_state
    return state


def _msg_with_tool_calls(has_calls):
    m = MagicMock()
    m.tool_calls = [{"id": "1"}] if has_calls else []
    return m


class TestShouldContinueAnalysis:
    """Tests for all should_continue_* analysis methods."""

    def test_market_with_tool_calls(self):
        cl = ConditionalLogic()
        state = _make_state(messages=[_msg_with_tool_calls(True)])
        assert cl.should_continue_market(state) == "tools_market"

    def test_market_without_tool_calls(self):
        cl = ConditionalLogic()
        state = _make_state(messages=[_msg_with_tool_calls(False)])
        assert cl.should_continue_market(state) == "Msg Clear Market"

    def test_social_with_tool_calls(self):
        cl = ConditionalLogic()
        state = _make_state(messages=[_msg_with_tool_calls(True)])
        assert cl.should_continue_social(state) == "tools_social"

    def test_social_without_tool_calls(self):
        cl = ConditionalLogic()
        state = _make_state(messages=[_msg_with_tool_calls(False)])
        assert cl.should_continue_social(state) == "Msg Clear Social"

    def test_news_with_tool_calls(self):
        cl = ConditionalLogic()
        state = _make_state(messages=[_msg_with_tool_calls(True)])
        assert cl.should_continue_news(state) == "tools_news"

    def test_news_without_tool_calls(self):
        cl = ConditionalLogic()
        state = _make_state(messages=[_msg_with_tool_calls(False)])
        assert cl.should_continue_news(state) == "Msg Clear News"

    def test_fundamentals_with_tool_calls(self):
        cl = ConditionalLogic()
        state = _make_state(messages=[_msg_with_tool_calls(True)])
        assert cl.should_continue_fundamentals(state) == "tools_fundamentals"

    def test_fundamentals_without_tool_calls(self):
        cl = ConditionalLogic()
        state = _make_state(messages=[_msg_with_tool_calls(False)])
        assert cl.should_continue_fundamentals(state) == "Msg Clear Fundamentals"


class TestCryptoAnalysis:
    def test_crypto_technical_with_tools(self):
        cl = ConditionalLogic()
        state = _make_state(messages=[_msg_with_tool_calls(True)])
        assert cl.should_continue_crypto_technical(state) == "tools_crypto_technical"

    def test_crypto_technical_without_tools(self):
        cl = ConditionalLogic()
        state = _make_state(messages=[_msg_with_tool_calls(False)])
        assert cl.should_continue_crypto_technical(state) == "Msg Clear Crypto_technical"

    def test_crypto_derivatives(self):
        cl = ConditionalLogic()
        assert cl.should_continue_crypto_derivatives(_make_state(messages=[_msg_with_tool_calls(True)])) == "tools_crypto_derivatives"
        assert cl.should_continue_crypto_derivatives(_make_state(messages=[_msg_with_tool_calls(False)])) == "Msg Clear Crypto_derivatives"

    def test_crypto_news(self):
        cl = ConditionalLogic()
        assert cl.should_continue_crypto_news(_make_state(messages=[_msg_with_tool_calls(True)])) == "tools_crypto_news"
        assert cl.should_continue_crypto_news(_make_state(messages=[_msg_with_tool_calls(False)])) == "Msg Clear Crypto_news"

    def test_crypto_fundamentals(self):
        cl = ConditionalLogic()
        assert cl.should_continue_crypto_fundamentals(_make_state(messages=[_msg_with_tool_calls(True)])) == "tools_crypto_fundamentals"
        assert cl.should_continue_crypto_fundamentals(_make_state(messages=[_msg_with_tool_calls(False)])) == "Msg Clear Crypto_fundamentals"

    def test_crypto_social(self):
        cl = ConditionalLogic()
        assert cl.should_continue_crypto_social(_make_state(messages=[_msg_with_tool_calls(True)])) == "tools_crypto_social"
        assert cl.should_continue_crypto_social(_make_state(messages=[_msg_with_tool_calls(False)])) == "Msg Clear Crypto_social"


class TestShouldContinueDebate:
    def test_below_threshold_bull_current(self):
        cl = ConditionalLogic(max_debate_rounds=2)
        state = _make_state(debate_state={"count": 1, "current_response": "Bull analysis..."})
        assert cl.should_continue_debate(state) == "Bear Researcher"

    def test_below_threshold_non_bull(self):
        cl = ConditionalLogic(max_debate_rounds=2)
        state = _make_state(debate_state={"count": 1, "current_response": "Bear counter..."})
        assert cl.should_continue_debate(state) == "Bull Researcher"

    def test_at_threshold_returns_research_manager(self):
        cl = ConditionalLogic(max_debate_rounds=2)
        state = _make_state(debate_state={"count": 4, "current_response": "Bull analysis"})
        assert cl.should_continue_debate(state) == "Research Manager"

    def test_above_threshold(self):
        cl = ConditionalLogic(max_debate_rounds=1)
        state = _make_state(debate_state={"count": 5, "current_response": "x"})
        assert cl.should_continue_debate(state) == "Research Manager"


class TestShouldContinueRiskAnalysis:
    def test_crypto_2party_bull_below_threshold(self):
        cl = ConditionalLogic(max_risk_discuss_rounds=2)
        state = _make_state(risk_state={"count": 1, "latest_speaker": "Bull Analyst"})
        assert cl.should_continue_risk_analysis(state) == "Bear Analyst"

    def test_crypto_2party_bear_below_threshold(self):
        cl = ConditionalLogic(max_risk_discuss_rounds=2)
        state = _make_state(risk_state={"count": 1, "latest_speaker": "Bear Analyst"})
        assert cl.should_continue_risk_analysis(state) == "Bull Analyst"

    def test_crypto_2party_at_threshold(self):
        cl = ConditionalLogic(max_risk_discuss_rounds=2)
        state = _make_state(risk_state={"count": 4, "latest_speaker": "Bull Analyst"})
        assert cl.should_continue_risk_analysis(state) == "Portfolio Manager"

    def test_stock_3party_aggressive(self):
        cl = ConditionalLogic(max_risk_discuss_rounds=2)
        state = _make_state(risk_state={"count": 1, "latest_speaker": "Aggressive Analyst"})
        assert cl.should_continue_risk_analysis(state) == "Conservative Analyst"

    def test_stock_3party_conservative(self):
        cl = ConditionalLogic(max_risk_discuss_rounds=2)
        state = _make_state(risk_state={"count": 1, "latest_speaker": "Conservative Analyst"})
        assert cl.should_continue_risk_analysis(state) == "Neutral Analyst"

    def test_stock_3party_neutral(self):
        cl = ConditionalLogic(max_risk_discuss_rounds=2)
        state = _make_state(risk_state={"count": 1, "latest_speaker": "Neutral Analyst"})
        assert cl.should_continue_risk_analysis(state) == "Aggressive Analyst"

    def test_stock_3party_at_threshold(self):
        cl = ConditionalLogic(max_risk_discuss_rounds=2)
        state = _make_state(risk_state={"count": 6, "latest_speaker": "Aggressive Analyst"})
        assert cl.should_continue_risk_analysis(state) == "Portfolio Manager"
