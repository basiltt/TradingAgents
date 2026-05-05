"""Tests for tradingagents.agents.risk_mgmt — Phase 1 unit tests."""

from unittest.mock import MagicMock


def _make_risk_state(**overrides):
    defaults = {
        "history": "",
        "aggressive_history": "",
        "conservative_history": "",
        "neutral_history": "",
        "latest_speaker": "",
        "current_aggressive_response": "",
        "current_conservative_response": "",
        "current_neutral_response": "",
        "count": 0,
    }
    defaults.update(overrides)
    return defaults


def _make_full_state(risk_state=None, **overrides):
    state = {
        "market_report": "Market data",
        "sentiment_report": "Sentiment data",
        "news_report": "News data",
        "fundamentals_report": "Fundamentals data",
        "trader_investment_plan": "Buy 100 shares",
        "risk_debate_state": risk_state or _make_risk_state(),
    }
    state.update(overrides)
    return state


class TestAggressiveDebator:
    def test_creates_callable(self):
        from tradingagents.agents.risk_mgmt.aggressive_debator import create_aggressive_debator
        node = create_aggressive_debator(MagicMock())
        assert callable(node)

    def test_invokes_llm_and_returns_state(self):
        from tradingagents.agents.risk_mgmt.aggressive_debator import create_aggressive_debator
        llm = MagicMock()
        llm.invoke.return_value = MagicMock(content="High risk, high reward")
        node = create_aggressive_debator(llm)
        result = node(_make_full_state(_make_risk_state(count=1)))
        ds = result["risk_debate_state"]
        assert "Aggressive Analyst" in ds["current_aggressive_response"]
        assert ds["count"] == 2
        assert ds["latest_speaker"] == "Aggressive"

    def test_preserves_other_histories(self):
        from tradingagents.agents.risk_mgmt.aggressive_debator import create_aggressive_debator
        llm = MagicMock()
        llm.invoke.return_value = MagicMock(content="Go big")
        node = create_aggressive_debator(llm)
        state = _make_full_state(_make_risk_state(
            conservative_history="prior conservative",
            neutral_history="prior neutral",
            count=0,
        ))
        result = node(state)
        assert result["risk_debate_state"]["conservative_history"] == "prior conservative"
        assert result["risk_debate_state"]["neutral_history"] == "prior neutral"


class TestConservativeDebator:
    def test_invokes_llm_and_returns_state(self):
        from tradingagents.agents.risk_mgmt.conservative_debator import create_conservative_debator
        llm = MagicMock()
        llm.invoke.return_value = MagicMock(content="Caution advised")
        node = create_conservative_debator(llm)
        result = node(_make_full_state(_make_risk_state(count=2)))
        ds = result["risk_debate_state"]
        assert "Conservative Analyst" in ds["current_conservative_response"]
        assert ds["count"] == 3
        assert ds["latest_speaker"] == "Conservative"


class TestNeutralDebator:
    def test_invokes_llm_and_returns_state(self):
        from tradingagents.agents.risk_mgmt.neutral_debator import create_neutral_debator
        llm = MagicMock()
        llm.invoke.return_value = MagicMock(content="Balanced view")
        node = create_neutral_debator(llm)
        result = node(_make_full_state(_make_risk_state(count=3)))
        ds = result["risk_debate_state"]
        assert "Neutral Analyst" in ds["current_neutral_response"]
        assert ds["count"] == 4
        assert ds["latest_speaker"] == "Neutral"
