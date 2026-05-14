"""Tests for Phase 4: Risk Manager, structured PM output, prompt improvements."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from langchain_core.messages import AIMessage

from tradingagents.agents.schemas import (
    RiskVerdict,
    RiskFinding,
    RiskAssessment,
    render_risk_assessment,
)


class TestRiskSchemas:
    def test_risk_verdict_values(self):
        assert RiskVerdict.APPROVE.value == "Approve"
        assert RiskVerdict.MODIFY.value == "Modify"
        assert RiskVerdict.REJECT.value == "Reject"

    def test_risk_assessment_creation(self):
        assessment = RiskAssessment(
            overall_verdict=RiskVerdict.APPROVE,
            risk_score=25,
            findings=[
                RiskFinding(check="Position Size", verdict=RiskVerdict.APPROVE, detail="OK"),
            ],
            summary="Low risk trade.",
        )
        assert assessment.risk_score == 25
        assert len(assessment.findings) == 1

    def test_risk_score_bounds(self):
        with pytest.raises(Exception):
            RiskAssessment(
                overall_verdict=RiskVerdict.APPROVE,
                risk_score=101,
                findings=[],
                summary="Bad",
            )

    def test_render_risk_assessment(self):
        assessment = RiskAssessment(
            overall_verdict=RiskVerdict.MODIFY,
            risk_score=60,
            findings=[
                RiskFinding(check="Leverage", verdict=RiskVerdict.MODIFY, detail="Too high"),
            ],
            adjusted_leverage=5,
            summary="Reduce leverage.",
        )
        text = render_risk_assessment(assessment)
        assert "MODIFY" in text or "Modify" in text
        assert "60/100" in text
        assert "5x" in text


class TestRiskManagerAgent:
    def test_creates_node(self):
        from tradingagents.agents.risk.risk_manager import create_risk_manager
        llm = MagicMock()
        node = create_risk_manager(llm)
        assert callable(node)

    def test_fail_closed_on_freetext(self):
        from tradingagents.agents.risk.risk_manager import create_risk_manager

        llm = MagicMock()
        llm.invoke.return_value = AIMessage(content="This trade is risky")
        structured = MagicMock()
        structured.invoke.return_value = AIMessage(content="This trade is risky")
        llm.with_structured_output.return_value = structured

        node = create_risk_manager(llm)
        state = {
            "company_of_interest": "BTCUSDT",
            "crypto_interval": "15",
            "trader_investment_plan": "Long BTC 10x",
            "current_price_context": "Last: $100000",
            "max_leverage": 20,
            "market_microstructure": {},
            "risk_debate_state": {"history": ""},
        }
        result = node(state)
        assert result["_risk_manager_verdict"] == "Reject"


class TestCryptoPMStructuredOutput:
    def test_returns_pm_signal_data(self):
        from tradingagents.agents.crypto_analysts import create_crypto_portfolio_manager

        llm = MagicMock()
        llm.invoke.return_value = AIMessage(content="Final: Buy BTC 3x")
        structured = MagicMock()
        structured.invoke.return_value = AIMessage(content="Final: Buy BTC 3x")
        llm.with_structured_output.return_value = structured

        node = create_crypto_portfolio_manager(llm)
        state = {
            "company_of_interest": "BTCUSDT",
            "crypto_interval": "15",
            "current_price_context": "Last: $100000",
            "investment_plan": "Buy BTC",
            "trader_investment_plan": "Long BTC",
            "risk_debate_state": {
                "history": "Bull: good. Bear: risky.",
                "aggressive_history": "",
                "conservative_history": "",
                "neutral_history": "",
                "current_aggressive_response": "",
                "current_conservative_response": "",
                "current_neutral_response": "",
                "judge_decision": "",
                "count": 2,
            },
            "past_context": "",
            "max_leverage": 20,
            "risk_manager_result": "",
        }
        result = node(state)
        assert "final_trade_decision" in result
        assert "_pm_signal_data" in result
