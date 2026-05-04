"""Tests for tradingagents.agents.utils.agent_utils — Phase 1 unit tests."""

from unittest.mock import patch, MagicMock
import pytest


class TestGetLanguageInstruction:
    @patch("tradingagents.dataflows.config.get_config", return_value={"output_language": "English"})
    def test_english_returns_empty(self, mock_cfg):
        from tradingagents.agents.utils.agent_utils import get_language_instruction
        assert get_language_instruction() == ""

    @patch("tradingagents.dataflows.config.get_config", return_value={"output_language": "Japanese"})
    def test_non_english_returns_instruction(self, mock_cfg):
        from tradingagents.agents.utils.agent_utils import get_language_instruction
        result = get_language_instruction()
        assert "Japanese" in result

    @patch("tradingagents.dataflows.config.get_config", return_value={})
    def test_default_is_english(self, mock_cfg):
        from tradingagents.agents.utils.agent_utils import get_language_instruction
        assert get_language_instruction() == ""

    @patch("tradingagents.dataflows.config.get_config", return_value={"output_language": "  english  "})
    def test_case_insensitive_whitespace(self, mock_cfg):
        from tradingagents.agents.utils.agent_utils import get_language_instruction
        assert get_language_instruction() == ""


class TestBuildInstrumentContext:
    def test_contains_ticker(self):
        from tradingagents.agents.utils.agent_utils import build_instrument_context
        result = build_instrument_context("AAPL.TO")
        assert "AAPL.TO" in result

    def test_mentions_exchange_suffix(self):
        from tradingagents.agents.utils.agent_utils import build_instrument_context
        result = build_instrument_context("AAPL")
        assert "exchange suffix" in result.lower() or ".TO" in result


class TestCreateMsgDelete:
    def test_returns_removal_and_placeholder(self):
        from tradingagents.agents.utils.agent_utils import create_msg_delete
        from langchain_core.messages import HumanMessage, RemoveMessage

        delete_fn = create_msg_delete()
        msg1 = MagicMock()
        msg1.id = "msg-1"
        msg2 = MagicMock()
        msg2.id = "msg-2"

        result = delete_fn({"messages": [msg1, msg2]})
        ops = result["messages"]
        assert len(ops) == 3  # 2 removals + 1 placeholder
        assert isinstance(ops[0], RemoveMessage)
        assert isinstance(ops[1], RemoveMessage)
        assert isinstance(ops[2], HumanMessage)
        assert ops[2].content == "Continue"

    def test_empty_messages(self):
        from tradingagents.agents.utils.agent_utils import create_msg_delete

        delete_fn = create_msg_delete()
        result = delete_fn({"messages": []})
        assert len(result["messages"]) == 1  # only placeholder
