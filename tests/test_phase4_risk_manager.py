"""Tests for Phase 4: Risk Manager, structured PM output, prompt improvements."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from unittest.mock import MagicMock, patch
from langchain_core.messages import AIMessage

from tradingagents.agents.schemas import (
    RiskVerdict,
    RiskFinding,
    RiskAssessment,
    render_risk_assessment,
)
from tradingagents.agents.utils.structured import bind_structured, invoke_structured_or_freetext


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
        with pytest.raises(ValidationError):
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


class TestRiskScoreLowerBound:
    def test_negative_risk_score_rejected(self):
        with pytest.raises(ValidationError):
            RiskAssessment(
                overall_verdict=RiskVerdict.APPROVE,
                risk_score=-1,
                findings=[],
                summary="Bad",
            )


class TestBindStructured:
    def test_returns_bound_llm(self):
        llm = MagicMock()
        result = bind_structured(llm, RiskAssessment, "Test")
        assert result is not None
        assert llm.with_structured_output.call_count == 2

    def test_returns_none_on_not_implemented(self):
        llm = MagicMock()
        llm.with_structured_output.side_effect = NotImplementedError
        result = bind_structured(llm, RiskAssessment, "Test")
        assert result is None

    def test_returns_none_on_attribute_error(self):
        llm = MagicMock()
        llm.with_structured_output.side_effect = AttributeError
        result = bind_structured(llm, RiskAssessment, "Test")
        assert result is None


class TestInvokeStructuredOrFreetext:
    def test_structured_success(self):
        obj = RiskAssessment(
            overall_verdict=RiskVerdict.APPROVE,
            risk_score=10,
            findings=[],
            summary="OK",
        )
        structured_llm = MagicMock()
        structured_llm.invoke.return_value = obj
        plain_llm = MagicMock()

        text, result = invoke_structured_or_freetext(
            structured_llm, plain_llm, "prompt",
            render=render_risk_assessment, agent_name="Test",
        )
        assert result is obj
        assert "Approve" in text or "APPROVE" in text

    def test_falls_back_on_exception(self):
        structured_llm = MagicMock()
        structured_llm.invoke.side_effect = Exception("parse error")
        plain_llm = MagicMock()
        plain_llm.invoke.return_value = AIMessage(content="fallback text")

        text, result = invoke_structured_or_freetext(
            structured_llm, plain_llm, "prompt",
            render=render_risk_assessment, agent_name="Test",
        )
        assert result is None
        assert text == "fallback text"

    def test_falls_back_when_structured_none(self):
        plain_llm = MagicMock()
        plain_llm.invoke.return_value = AIMessage(content="freetext")

        text, result = invoke_structured_or_freetext(
            None, plain_llm, "prompt",
            render=render_risk_assessment, agent_name="Test",
        )
        assert result is None
        assert text == "freetext"


class TestRiskManagerOverrideLogic:
    def _make_node(self):
        from tradingagents.agents.risk.risk_manager import create_risk_manager
        llm = MagicMock()
        return create_risk_manager(llm, max_leverage=10), llm

    def _base_state(self):
        return {
            "company_of_interest": "BTCUSDT",
            "crypto_interval": "15",
            "trader_investment_plan": "Long BTC 5x",
            "current_price_context": "Last: $100000",
            "max_leverage": 10,
            "market_microstructure": {},
            "risk_debate_state": {"history": ""},
        }

    def test_reject_finding_overrides_approve(self):
        node, llm = self._make_node()
        assessment = RiskAssessment(
            overall_verdict=RiskVerdict.APPROVE,
            risk_score=80,
            findings=[
                RiskFinding(check="Leverage", verdict=RiskVerdict.REJECT, detail="Too high"),
            ],
            summary="Rejected due to leverage.",
        )
        with patch(
            "tradingagents.agents.risk.risk_manager.invoke_structured_or_freetext",
            return_value=(render_risk_assessment(assessment), assessment),
        ):
            result = node(self._base_state())
        assert result["_risk_manager_verdict"] == "Reject"

    def test_modify_finding_sets_modify(self):
        node, llm = self._make_node()
        assessment = RiskAssessment(
            overall_verdict=RiskVerdict.APPROVE,
            risk_score=50,
            findings=[
                RiskFinding(check="Funding", verdict=RiskVerdict.MODIFY, detail="High cost"),
            ],
            summary="Modify leverage.",
        )
        with patch(
            "tradingagents.agents.risk.risk_manager.invoke_structured_or_freetext",
            return_value=(render_risk_assessment(assessment), assessment),
        ):
            result = node(self._base_state())
        assert result["_risk_manager_verdict"] == "Modify"

    def test_adjusted_leverage_capped(self):
        node, llm = self._make_node()
        assessment = RiskAssessment(
            overall_verdict=RiskVerdict.MODIFY,
            risk_score=60,
            findings=[
                RiskFinding(check="Leverage", verdict=RiskVerdict.MODIFY, detail="Reduce leverage"),
            ],
            adjusted_leverage=50,
            summary="Reduce leverage.",
        )
        with patch(
            "tradingagents.agents.risk.risk_manager.invoke_structured_or_freetext",
            return_value=(render_risk_assessment(assessment), assessment),
        ):
            result = node(self._base_state())
        assert result["_risk_manager_verdict"] == "Modify"

    def test_all_approve_passthrough(self):
        node, llm = self._make_node()
        assessment = RiskAssessment(
            overall_verdict=RiskVerdict.APPROVE,
            risk_score=10,
            findings=[
                RiskFinding(check="Size", verdict=RiskVerdict.APPROVE, detail="OK"),
            ],
            summary="All clear.",
        )
        with patch(
            "tradingagents.agents.risk.risk_manager.invoke_structured_or_freetext",
            return_value=(render_risk_assessment(assessment), assessment),
        ):
            result = node(self._base_state())
        assert result["_risk_manager_verdict"] == "Approve"

    def test_empty_findings_rejected(self):
        """LLM returning empty findings list must be rejected (fail-closed)."""
        node, llm = self._make_node()
        assessment = RiskAssessment(
            overall_verdict=RiskVerdict.APPROVE,
            risk_score=10,
            findings=[],
            summary="All clear.",
        )
        with patch(
            "tradingagents.agents.risk.risk_manager.invoke_structured_or_freetext",
            return_value=(render_risk_assessment(assessment), assessment),
        ):
            result = node(self._base_state())
        assert result["_risk_manager_verdict"] == "Reject"
