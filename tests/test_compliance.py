"""Tests for the Compliance Officer and Execution Monitor agents."""

from unittest.mock import MagicMock

import pytest

from tradingagents.agents.compliance.compliance_officer import create_compliance_officer
from tradingagents.agents.compliance.execution_monitor import create_execution_monitor
from tradingagents.agents.schemas import (
    ComplianceCheck,
    ComplianceFinding,
    ComplianceVerdict,
    render_compliance_check,
)


# ---------------------------------------------------------------------------
# Schema + render tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestComplianceSchemas:
    def test_compliance_check_pass(self):
        check = ComplianceCheck(
            overall_verdict=ComplianceVerdict.PASS,
            findings=[
                ComplianceFinding(
                    check="Position Size",
                    verdict=ComplianceVerdict.PASS,
                    detail="5% is within the 10% limit.",
                ),
            ],
            summary="All checks passed.",
        )
        md = render_compliance_check(check)
        assert "**Overall Verdict**: Pass" in md
        assert "**Position Size** [Pass]" in md
        assert "**Summary**: All checks passed." in md

    def test_compliance_check_flag(self):
        check = ComplianceCheck(
            overall_verdict=ComplianceVerdict.FLAG,
            findings=[
                ComplianceFinding(
                    check="Price Sanity",
                    verdict=ComplianceVerdict.FLAG,
                    detail="Entry 6% from current price.",
                ),
                ComplianceFinding(
                    check="Stop-Loss Presence",
                    verdict=ComplianceVerdict.PASS,
                    detail="Stop-loss defined at 94000.",
                ),
            ],
            summary="One concern flagged.",
        )
        md = render_compliance_check(check)
        assert "**Overall Verdict**: Flag" in md
        assert "[Flag]" in md
        assert "[Pass]" in md

    def test_compliance_check_block(self):
        check = ComplianceCheck(
            overall_verdict=ComplianceVerdict.BLOCK,
            findings=[
                ComplianceFinding(
                    check="Stop-Loss Presence",
                    verdict=ComplianceVerdict.BLOCK,
                    detail="No stop-loss defined.",
                ),
            ],
            summary="Trade blocked: missing stop-loss.",
        )
        md = render_compliance_check(check)
        assert "**Overall Verdict**: Block" in md
        assert "[Block]" in md


# ---------------------------------------------------------------------------
# Compliance Officer agent tests
# ---------------------------------------------------------------------------


def _make_compliance_state():
    return {
        "company_of_interest": "BTCUSDT",
        "trader_investment_plan": '{"direction": "Long", "entry_price": 95000}',
        "current_price_context": "Last Price: 95000.0",
        "past_context": "",
    }


@pytest.mark.unit
class TestComplianceOfficerAgent:
    def test_structured_path_produces_rendered_output(self):
        check = ComplianceCheck(
            overall_verdict=ComplianceVerdict.PASS,
            findings=[
                ComplianceFinding(
                    check="Position Size",
                    verdict=ComplianceVerdict.PASS,
                    detail="Within limits.",
                ),
            ],
            summary="All clear.",
        )
        structured_mock = MagicMock()
        structured_mock.invoke.return_value = check
        llm = MagicMock()
        llm.with_structured_output.return_value = structured_mock

        officer = create_compliance_officer(llm)
        result = officer(_make_compliance_state())

        assert "Pass" in result["compliance_result"]
        assert result["_compliance_verdict"] == "Pass"

    def test_blocked_trade_sets_block_verdict(self):
        check = ComplianceCheck(
            overall_verdict=ComplianceVerdict.BLOCK,
            findings=[
                ComplianceFinding(
                    check="Stop-Loss",
                    verdict=ComplianceVerdict.BLOCK,
                    detail="Missing.",
                ),
            ],
            summary="Blocked.",
        )
        structured_mock = MagicMock()
        structured_mock.invoke.return_value = check
        llm = MagicMock()
        llm.with_structured_output.return_value = structured_mock

        officer = create_compliance_officer(llm)
        result = officer(_make_compliance_state())

        assert result["_compliance_verdict"] == "Block"

    def test_programmatic_override_when_llm_hallucinates_pass(self):
        """Even if LLM sets overall_verdict=Pass, a Block finding forces Block."""
        check = ComplianceCheck(
            overall_verdict=ComplianceVerdict.PASS,
            findings=[
                ComplianceFinding(
                    check="Position Size",
                    verdict=ComplianceVerdict.PASS,
                    detail="OK.",
                ),
                ComplianceFinding(
                    check="Leverage Cap",
                    verdict=ComplianceVerdict.BLOCK,
                    detail="50x exceeds 20x maximum.",
                ),
            ],
            summary="Looks fine.",
        )
        structured_mock = MagicMock()
        structured_mock.invoke.return_value = check
        llm = MagicMock()
        llm.with_structured_output.return_value = structured_mock

        officer = create_compliance_officer(llm)
        result = officer(_make_compliance_state())

        assert result["_compliance_verdict"] == "Block"

    def test_fallback_freetext_detects_block(self):
        llm = MagicMock()
        llm.with_structured_output.side_effect = NotImplementedError("unsupported")
        llm.invoke.return_value = MagicMock(
            content="BLOCK: No stop-loss defined for this Long trade."
        )

        officer = create_compliance_officer(llm)
        result = officer(_make_compliance_state())

        assert result["_compliance_verdict"] == "Block"

    def test_fallback_freetext_defaults_to_block(self):
        """Freetext fallback defaults to BLOCK (fail-closed) for safety."""
        llm = MagicMock()
        llm.with_structured_output.side_effect = NotImplementedError("unsupported")
        llm.invoke.return_value = MagicMock(
            content="FLAG: Entry price 6% away from current."
        )

        officer = create_compliance_officer(llm)
        result = officer(_make_compliance_state())

        # Even though text says "flag", structured parse failure = BLOCK
        assert result["_compliance_verdict"] == "Block"

    def test_fallback_freetext_pass_text_gets_flag(self):
        """When freetext clearly says 'pass' with no 'block', verdict is FLAG (not PASS)."""
        llm = MagicMock()
        llm.with_structured_output.side_effect = NotImplementedError("unsupported")
        llm.invoke.return_value = MagicMock(
            content="All checks pass. The trade meets all requirements."
        )

        officer = create_compliance_officer(llm)
        result = officer(_make_compliance_state())

        assert result["_compliance_verdict"] == "Flag"


# ---------------------------------------------------------------------------
# Execution Monitor agent tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExecutionMonitorAgent:
    def test_appends_notes_to_final_decision(self):
        llm = MagicMock()
        llm.invoke.return_value = MagicMock(
            content="Slippage est. 0.1%. Execute during high-volume window."
        )

        state = {
            "company_of_interest": "BTCUSDT",
            "current_price_context": "Last Price: 95000.0",
            "final_trade_decision": "APPROVE: Long BTC at 95000 with 5x leverage.",
            "trader_investment_plan": '{"direction": "Long"}',
            "compliance_result": "All checks passed.",
        }

        monitor = create_execution_monitor(llm)
        result = monitor(state)

        assert "Execution Monitor Notes" in result["final_trade_decision"]
        assert "Slippage" in result["execution_notes"]
        assert result["sender"] == "Execution Monitor"
        assert "APPROVE" in result["final_trade_decision"]

    def test_handles_missing_optional_fields(self):
        llm = MagicMock()
        llm.invoke.return_value = MagicMock(content="No concerns.")

        state = {
            "company_of_interest": "NVDA",
            "final_trade_decision": "Hold position.",
        }

        monitor = create_execution_monitor(llm)
        result = monitor(state)

        assert "No concerns." in result["execution_notes"]
