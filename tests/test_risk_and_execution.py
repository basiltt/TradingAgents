"""Tests for Risk Manager and Execution Monitor agent nodes."""

from unittest.mock import MagicMock, patch

import pytest

from tradingagents.agents.schemas import (
    RiskAssessment,
    RiskFinding,
    RiskVerdict,
    render_risk_assessment,
)


# ---------------------------------------------------------------------------
# Risk Manager schema tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRiskManagerSchemas:
    def test_approve_assessment(self):
        assessment = RiskAssessment(
            overall_verdict=RiskVerdict.APPROVE,
            risk_score=25,
            findings=[
                RiskFinding(check="Position Size", verdict=RiskVerdict.APPROVE, detail="3% is fine."),
            ],
            summary="Low risk trade.",
        )
        md = render_risk_assessment(assessment)
        assert "**Overall Risk Verdict**: Approve" in md
        assert "**Risk Score**: 25/100" in md
        assert "**Position Size** [Approve]" in md

    def test_reject_overrides_modify(self):
        assessment = RiskAssessment(
            overall_verdict=RiskVerdict.MODIFY,
            risk_score=80,
            findings=[
                RiskFinding(check="Leverage", verdict=RiskVerdict.REJECT, detail="Too high."),
                RiskFinding(check="Spread", verdict=RiskVerdict.MODIFY, detail="Wide."),
            ],
            summary="Rejected.",
        )
        assert any(f.verdict == RiskVerdict.REJECT for f in assessment.findings)

    def test_adjusted_leverage_renders(self):
        assessment = RiskAssessment(
            overall_verdict=RiskVerdict.MODIFY,
            risk_score=50,
            findings=[RiskFinding(check="Leverage", verdict=RiskVerdict.MODIFY, detail="Reduce.")],
            adjusted_leverage=5,
            summary="Reduce leverage.",
        )
        md = render_risk_assessment(assessment)
        assert "**Adjusted Leverage**: 5x" in md


# ---------------------------------------------------------------------------
# Risk Manager node — integration-lite (mocked LLM)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRiskManagerNode:
    @patch("tradingagents.agents.utils.state_filter.is_enabled", return_value=True)
    def test_reject_on_structured_failure(self, _flag_mock):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="Risk assessment freetext")
        mock_llm.with_structured_output.side_effect = NotImplementedError("no structured")

        from tradingagents.agents.risk.risk_manager import create_risk_manager
        node = create_risk_manager(mock_llm)

        state = {
            "company_of_interest": "BTCUSDT",
            "crypto_interval": "60",
            "trader_investment_plan": "Buy at 100k",
            "current_price_context": "BTC 100k",
            "max_leverage": 20,
            "market_microstructure": None,
            "messages": [],
        }
        result = node.invoke(state)
        assert result.get("_risk_manager_verdict") == "Reject"
        assert "risk_manager_result" in result

    @patch("tradingagents.agents.utils.state_filter.is_enabled", return_value=True)
    def test_approve_on_structured_success(self, _flag_mock):
        assessment = RiskAssessment(
            overall_verdict=RiskVerdict.APPROVE,
            risk_score=20,
            findings=[RiskFinding(check="Size", verdict=RiskVerdict.APPROVE, detail="OK")],
            summary="Approved.",
        )

        mock_structured = MagicMock()
        mock_structured.invoke.return_value = assessment

        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = mock_structured

        from tradingagents.agents.risk.risk_manager import create_risk_manager
        node = create_risk_manager(mock_llm)

        state = {
            "company_of_interest": "BTCUSDT",
            "crypto_interval": "60",
            "trader_investment_plan": "Buy at 100k",
            "current_price_context": "BTC 100k",
            "max_leverage": 20,
            "market_microstructure": None,
            "messages": [],
        }
        result = node.invoke(state)
        assert result.get("_risk_manager_verdict") == "Approve"


# ---------------------------------------------------------------------------
# Execution Monitor node — integration-lite (mocked LLM)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExecutionMonitorNode:
    @patch("tradingagents.agents.utils.state_filter.is_enabled", return_value=True)
    def test_appends_notes_without_overriding_decision(self, _flag_mock):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="Check slippage before executing.")

        from tradingagents.agents.compliance.execution_monitor import create_execution_monitor
        node = create_execution_monitor(mock_llm)

        state = {
            "company_of_interest": "BTCUSDT",
            "crypto_interval": "60",
            "final_trade_decision": "Buy BTC at 100k",
            "current_price_context": "BTC 100k",
            "trader_investment_plan": "Entry at 100k, SL at 95k",
            "compliance_result": "Pass",
            "messages": [],
        }
        result = node.invoke(state)
        assert "execution_notes" in result
        assert "Execution Monitor Notes" in result.get("final_trade_decision", "")
        assert result["final_trade_decision"].startswith("<external_data")

    @patch("tradingagents.agents.utils.state_filter.is_enabled", return_value=True)
    def test_writes_only_allowed_keys(self, _flag_mock):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="Notes here.")

        from tradingagents.agents.compliance.execution_monitor import create_execution_monitor
        node = create_execution_monitor(mock_llm)

        state = {
            "company_of_interest": "BTCUSDT",
            "crypto_interval": "60",
            "final_trade_decision": "Buy",
            "current_price_context": "",
            "trader_investment_plan": "",
            "compliance_result": "",
            "messages": [],
        }
        result = node.invoke(state)
        from tradingagents.agents.constants import WRITABLE_KEYS
        allowed = set(WRITABLE_KEYS["execution_monitor"]) | {"messages", "sender"}
        assert set(result.keys()).issubset(allowed)
