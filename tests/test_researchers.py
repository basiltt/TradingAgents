"""Tests for tradingagents.agents.researchers — Phase 1 unit tests."""

from unittest.mock import MagicMock


def _make_debate_state(**overrides):
    defaults = {
        "history": "",
        "bull_history": "",
        "bear_history": "",
        "current_response": "",
        "count": 0,
    }
    defaults.update(overrides)
    return defaults


def _make_full_state(debate_state=None, **overrides):
    state = {
        "market_report": "Market is up 2%",
        "sentiment_report": "Sentiment positive",
        "news_report": "Good earnings",
        "fundamentals_report": "Strong balance sheet",
        "investment_debate_state": debate_state or _make_debate_state(),
    }
    state.update(overrides)
    return state


class TestBullResearcher:
    def test_creates_callable(self):
        from tradingagents.agents.researchers.bull_researcher import create_bull_researcher
        llm = MagicMock()
        node = create_bull_researcher(llm)
        assert hasattr(node, "invoke")

    def test_invokes_llm_and_returns_state(self):
        from tradingagents.agents.researchers.bull_researcher import create_bull_researcher
        llm = MagicMock()
        llm.invoke.return_value = MagicMock(content="Strong growth ahead")
        node = create_bull_researcher(llm)
        state = _make_full_state(_make_debate_state(count=1, current_response="Bear says risk"))
        result = node.invoke(state)
        assert "investment_debate_state" in result
        ds = result["investment_debate_state"]
        assert "Bull Analyst: Strong growth ahead" in ds["current_response"]
        assert ds["count"] == 2
        assert "Strong growth ahead" in ds["bull_history"]

    def test_preserves_bear_history(self):
        from tradingagents.agents.researchers.bull_researcher import create_bull_researcher
        llm = MagicMock()
        llm.invoke.return_value = MagicMock(content="Bull point")
        node = create_bull_researcher(llm)
        state = _make_full_state(_make_debate_state(bear_history="Prior bear arg", count=0))
        result = node.invoke(state)
        assert result["investment_debate_state"]["bear_history"] == "Prior bear arg"


class TestBearResearcher:
    def test_creates_callable(self):
        from tradingagents.agents.researchers.bear_researcher import create_bear_researcher
        llm = MagicMock()
        node = create_bear_researcher(llm)
        assert hasattr(node, "invoke")

    def test_invokes_llm_and_returns_state(self):
        from tradingagents.agents.researchers.bear_researcher import create_bear_researcher
        llm = MagicMock()
        llm.invoke.return_value = MagicMock(content="Risks are mounting")
        node = create_bear_researcher(llm)
        state = _make_full_state(_make_debate_state(count=1, current_response="Bull says buy"))
        result = node.invoke(state)
        ds = result["investment_debate_state"]
        assert "Bear Analyst: Risks are mounting" in ds["current_response"]
        assert ds["count"] == 2
        assert "Risks are mounting" in ds["bear_history"]

    def test_preserves_bull_history(self):
        from tradingagents.agents.researchers.bear_researcher import create_bear_researcher
        llm = MagicMock()
        llm.invoke.return_value = MagicMock(content="Bear point")
        node = create_bear_researcher(llm)
        state = _make_full_state(_make_debate_state(bull_history="Prior bull arg", count=0))
        result = node.invoke(state)
        assert result["investment_debate_state"]["bull_history"] == "Prior bull arg"
