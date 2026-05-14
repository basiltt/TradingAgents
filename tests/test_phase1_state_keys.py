"""Tests for Phase 1: State key rename + timeframe propagation."""

import pytest

from tradingagents.agents.constants import ReportKeys, READABLE_KEYS, WRITABLE_KEYS
from tradingagents.agents.utils.agent_states import (
    AgentState,
    CryptoRiskDebateState,
)
from tradingagents.config.feature_flags import FEATURE_FLAGS, is_enabled
from tradingagents.agents.utils.state_filter import filter_state_for_read, validate_state_write


class TestReportKeys:
    def test_all_keys_are_strings(self):
        for attr in dir(ReportKeys):
            if attr.startswith("_"):
                continue
            assert isinstance(getattr(ReportKeys, attr), str)

    def test_derivatives_key(self):
        assert ReportKeys.DERIVATIVES == "derivatives_report"

    def test_fundamentals_key(self):
        assert ReportKeys.FUNDAMENTALS == "crypto_fundamentals_report"


class TestAgentStateNewFields:
    def test_derivatives_report_field(self):
        assert "derivatives_report" in AgentState.__annotations__

    def test_risk_manager_result_field(self):
        assert "risk_manager_result" in AgentState.__annotations__

    def test_risk_manager_verdict_field(self):
        assert "_risk_manager_verdict" in AgentState.__annotations__

    def test_technical_levels_summary_field(self):
        assert "technical_levels_summary" in AgentState.__annotations__

    def test_market_microstructure_field(self):
        assert "market_microstructure" in AgentState.__annotations__

    def test_max_leverage_field(self):
        assert "max_leverage" in AgentState.__annotations__

    def test_crypto_risk_debate_state(self):
        s = CryptoRiskDebateState(
            bull_history="", bear_history="", history="", count=0,
        )
        assert s["count"] == 0


class TestFeatureFlags:
    def test_flags_are_immutable(self):
        with pytest.raises(TypeError):
            FEATURE_FLAGS["use_information_barriers"] = False  # type: ignore[index]

    def test_all_flags_default_enabled(self):
        for flag in FEATURE_FLAGS:
            assert FEATURE_FLAGS[flag] is True

    def test_is_enabled_returns_true(self):
        assert is_enabled("use_information_barriers") is True

    def test_is_enabled_unknown_flag(self):
        assert is_enabled("nonexistent_flag") is False

    def test_security_flag_critical_log(self, caplog):
        import types
        import tradingagents.config.feature_flags as ff

        original = ff.FEATURE_FLAGS
        ff.FEATURE_FLAGS = types.MappingProxyType({
            **dict(original), "use_information_barriers": False,
        })
        try:
            with caplog.at_level("CRITICAL"):
                result = is_enabled("use_information_barriers")
            assert result is False
            assert "DISABLED" in caplog.text
        finally:
            ff.FEATURE_FLAGS = original


class TestStateFilter:
    def test_read_filter_returns_allowed_keys(self):
        state = {"company_of_interest": "BTC", "market_report": "secret", "crypto_interval": "15"}
        filtered = filter_state_for_read(state, "trader")
        assert "company_of_interest" in filtered
        assert "crypto_interval" in filtered
        assert "market_report" not in filtered

    def test_read_filter_unknown_role_returns_empty(self):
        state = {"company_of_interest": "BTC"}
        assert filter_state_for_read(state, "hacker") == {}

    def test_read_filter_missing_key_no_error(self):
        state = {"company_of_interest": "BTC"}
        filtered = filter_state_for_read(state, "risk_manager")
        assert "market_microstructure" not in filtered

    def test_read_filter_deepcopy_isolation(self):
        inner = {"a": [1, 2, 3]}
        state = {"market_microstructure": inner, "company_of_interest": "BTC"}
        filtered = filter_state_for_read(state, "risk_manager")
        filtered["market_microstructure"]["a"].append(999)
        assert 999 not in state["market_microstructure"]["a"]

    def test_write_filter_allows_valid(self):
        updates = {"market_report": "report", "hack": "bad"}
        result = validate_state_write(updates, "technical_analyst")
        assert "market_report" in result
        assert "hack" not in result

    def test_write_filter_unknown_role_drops_all(self):
        assert validate_state_write({"x": 1}, "hacker") == {}

    def test_write_filter_passes_framework_keys(self):
        updates = {"market_report": "report", "messages": ["msg"], "sender": "X"}
        result = validate_state_write(updates, "technical_analyst")
        assert "messages" in result
        assert "sender" in result


class TestReadableWritableConsistency:
    def test_all_roles_have_both_allowlists(self):
        for role in READABLE_KEYS:
            assert role in WRITABLE_KEYS, f"{role} missing from WRITABLE_KEYS"

    def test_researchers_cannot_read_confluence(self):
        assert "confluence_summary" not in READABLE_KEYS["bull_researcher"]
        assert "confluence_summary" not in READABLE_KEYS["bear_researcher"]

    def test_risk_debaters_no_raw_reports(self):
        for report in ("market_report", "news_report", "sentiment_report"):
            assert report not in READABLE_KEYS["risk_bull_debater"]
            assert report not in READABLE_KEYS["risk_bear_debater"]

    def test_compliance_no_past_context(self):
        assert "past_context" not in READABLE_KEYS["compliance_officer"]

    def test_trader_no_confluence(self):
        assert "confluence_summary" not in READABLE_KEYS["trader"]
        assert "market_report" not in READABLE_KEYS["trader"]
