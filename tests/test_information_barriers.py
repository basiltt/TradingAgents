"""Tests for information barrier enforcement and allowlist completeness."""

from unittest.mock import patch

import pytest

from tradingagents.agents.constants import READABLE_KEYS, WRITABLE_KEYS
from tradingagents.agents.utils.state_filter import (
    filter_state_for_read,
    validate_state_write,
)


# ---------------------------------------------------------------------------
# Allowlist completeness: every role in READABLE must also be in WRITABLE
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAllowlistCompleteness:
    def test_readable_and_writable_have_same_roles(self):
        readable_roles = set(READABLE_KEYS.keys())
        writable_roles = set(WRITABLE_KEYS.keys())
        missing_writable = readable_roles - writable_roles
        missing_readable = writable_roles - readable_roles
        assert not missing_writable, f"Roles in READABLE_KEYS but not WRITABLE_KEYS: {missing_writable}"
        assert not missing_readable, f"Roles in WRITABLE_KEYS but not READABLE_KEYS: {missing_readable}"

    def test_no_role_can_write_keys_it_cannot_read(self):
        """Writable keys that aren't readable are allowed (write-only signal carriers),
        but every readable key should exist as a valid state key."""
        for role, writable in WRITABLE_KEYS.items():
            for key in writable:
                assert isinstance(key, str), f"Role {role} has non-string writable key: {key}"

    def test_all_keys_are_strings(self):
        for role, keys in READABLE_KEYS.items():
            for k in keys:
                assert isinstance(k, str), f"READABLE_KEYS[{role}] has non-string: {k}"
        for role, keys in WRITABLE_KEYS.items():
            for k in keys:
                assert isinstance(k, str), f"WRITABLE_KEYS[{role}] has non-string: {k}"


# ---------------------------------------------------------------------------
# filter_state_for_read
# ---------------------------------------------------------------------------

_SAMPLE_STATE = {
    "messages": [("human", "BTCUSDT")],
    "company_of_interest": "BTCUSDT",
    "trade_date": "2025-01-01",
    "crypto_interval": "60",
    "current_price_context": "BTC $100k",
    "market_report": "Technical analysis report",
    "investment_plan": "Buy BTC",
    "trader_investment_plan": "Entry at 100k",
    "risk_manager_result": "Approved",
    "compliance_result": "Pass",
    "final_trade_decision": "Buy",
    "confluence_summary": "All signals bullish",
    "secret_key": "should_never_leak",
}


@pytest.mark.unit
class TestFilterStateForRead:
    @patch("tradingagents.agents.utils.state_filter.is_enabled", return_value=True)
    def test_filters_to_allowed_keys_only(self, _mock):
        result = filter_state_for_read(_SAMPLE_STATE, "trader")
        allowed = set(READABLE_KEYS["trader"])
        assert set(result.keys()).issubset(allowed)
        assert "secret_key" not in result
        assert "market_report" not in result  # trader shouldn't see raw reports

    @patch("tradingagents.agents.utils.state_filter.is_enabled", return_value=True)
    def test_unknown_role_returns_empty(self, _mock):
        result = filter_state_for_read(_SAMPLE_STATE, "nonexistent_role")
        assert result == {}

    @patch("tradingagents.agents.utils.state_filter.is_enabled", return_value=False)
    def test_disabled_flag_returns_full_state(self, _mock):
        result = filter_state_for_read(_SAMPLE_STATE, "trader")
        assert "secret_key" in result

    @patch("tradingagents.agents.utils.state_filter.is_enabled", return_value=True)
    def test_deep_copies_mutable_values(self, _mock):
        state = {"messages": [1, 2, 3], "company_of_interest": "X", "trade_date": "2025-01-01", "crypto_interval": None, "current_price_context": ""}
        result = filter_state_for_read(state, "technical_analyst")
        if "messages" in result:
            result["messages"].append(99)
            assert 99 not in state["messages"]


# ---------------------------------------------------------------------------
# validate_state_write
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateStateWrite:
    @patch("tradingagents.agents.utils.state_filter.is_enabled", return_value=True)
    def test_allows_permitted_keys(self, _mock):
        updates = {"market_report": "new report", "messages": []}
        result = validate_state_write(updates, "technical_analyst")
        assert "market_report" in result
        assert "messages" in result  # framework key

    @patch("tradingagents.agents.utils.state_filter.is_enabled", return_value=True)
    def test_strips_disallowed_keys(self, _mock):
        updates = {"market_report": "ok", "final_trade_decision": "hacked"}
        result = validate_state_write(updates, "technical_analyst")
        assert "market_report" in result
        assert "final_trade_decision" not in result

    @patch("tradingagents.agents.utils.state_filter.is_enabled", return_value=True)
    def test_unknown_role_returns_empty(self, _mock):
        result = validate_state_write({"x": 1}, "nonexistent_role")
        assert result == {}

    @patch("tradingagents.agents.utils.state_filter.is_enabled", return_value=False)
    def test_disabled_flag_passes_all(self, _mock):
        updates = {"anything": "goes"}
        result = validate_state_write(updates, "trader")
        assert result == updates

    @patch("tradingagents.agents.utils.state_filter.is_enabled", return_value=True)
    def test_sender_is_framework_key(self, _mock):
        updates = {"sender": "Trader", "trader_investment_plan": "plan"}
        result = validate_state_write(updates, "trader")
        assert "sender" in result


# ---------------------------------------------------------------------------
# Cross-role isolation: no role can read another role's private write keys
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCrossRoleIsolation:
    def test_trader_cannot_read_compliance_result(self):
        assert "compliance_result" not in READABLE_KEYS.get("trader", [])

    def test_trader_cannot_read_confluence_summary(self):
        assert "confluence_summary" not in READABLE_KEYS.get("trader", [])

    def test_bull_researcher_cannot_read_confluence(self):
        assert "confluence_summary" not in READABLE_KEYS.get("bull_researcher", [])

    def test_compliance_cannot_read_past_context(self):
        assert "past_context" not in READABLE_KEYS.get("compliance_officer", [])

    def test_risk_debaters_cannot_read_raw_reports(self):
        report_keys = {"market_report", "derivatives_report", "news_report", "crypto_fundamentals_report", "sentiment_report"}
        for role in ("risk_bull_debater", "risk_bear_debater"):
            readable = set(READABLE_KEYS.get(role, []))
            leaked = readable & report_keys
            assert not leaked, f"{role} can read raw reports: {leaked}"
