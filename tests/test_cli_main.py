"""Tests for cli.main.MessageBuffer — Phase 1 unit tests."""

import pytest


class TestMessageBuffer:
    def _make(self):
        from cli.main import MessageBuffer
        return MessageBuffer()

    def test_init_defaults(self):
        buf = self._make()
        assert buf.current_report is None
        assert buf.final_report is None
        assert len(buf.messages) == 0

    def test_init_for_analysis_market_only(self):
        buf = self._make()
        buf.init_for_analysis(["market"])
        assert "Market Analyst" in buf.agent_status
        assert "News Analyst" not in buf.agent_status
        # Fixed agents always present
        assert "Trader" in buf.agent_status
        assert "Portfolio Manager" in buf.agent_status
        # Report sections
        assert "market_report" in buf.report_sections
        assert "news_report" not in buf.report_sections
        assert "investment_plan" in buf.report_sections  # always included

    def test_init_for_analysis_all_analysts(self):
        buf = self._make()
        buf.init_for_analysis(["market", "social", "news", "fundamentals"])
        assert "Market Analyst" in buf.agent_status
        assert "Social Analyst" in buf.agent_status
        assert "News Analyst" in buf.agent_status
        assert "Fundamentals Analyst" in buf.agent_status
        assert len(buf.report_sections) == 7

    def test_add_message(self):
        buf = self._make()
        buf.add_message("info", "hello")
        assert len(buf.messages) == 1
        assert buf.messages[0][2] == "hello"

    def test_add_tool_call(self):
        buf = self._make()
        buf.add_tool_call("my_tool", {"arg": 1})
        assert len(buf.tool_calls) == 1
        assert buf.tool_calls[0][1] == "my_tool"

    def test_update_agent_status(self):
        buf = self._make()
        buf.init_for_analysis(["market"])
        buf.update_agent_status("Market Analyst", "running")
        assert buf.agent_status["Market Analyst"] == "running"
        assert buf.current_agent == "Market Analyst"

    def test_update_agent_status_ignores_unknown(self):
        buf = self._make()
        buf.init_for_analysis(["market"])
        buf.update_agent_status("Nonexistent Agent", "running")
        assert "Nonexistent Agent" not in buf.agent_status

    def test_get_completed_reports_count_zero(self):
        buf = self._make()
        buf.init_for_analysis(["market"])
        assert buf.get_completed_reports_count() == 0

    def test_get_completed_reports_count_with_content_but_agent_not_done(self):
        buf = self._make()
        buf.init_for_analysis(["market"])
        buf.report_sections["market_report"] = "Some content"
        # Agent still pending
        assert buf.get_completed_reports_count() == 0

    def test_get_completed_reports_count_with_content_and_agent_done(self):
        buf = self._make()
        buf.init_for_analysis(["market"])
        buf.report_sections["market_report"] = "Some content"
        buf.agent_status["Market Analyst"] = "completed"
        assert buf.get_completed_reports_count() == 1

    def test_update_report_section(self):
        buf = self._make()
        buf.init_for_analysis(["market"])
        buf.update_report_section("market_report", "Analysis here")
        assert buf.report_sections["market_report"] == "Analysis here"
        assert buf.current_report is not None
        assert "Market Analysis" in buf.current_report

    def test_update_report_section_ignores_unknown(self):
        buf = self._make()
        buf.init_for_analysis(["market"])
        buf.update_report_section("unknown_section", "content")
        assert "unknown_section" not in buf.report_sections

    def test_final_report_assembles_all_sections(self):
        buf = self._make()
        buf.init_for_analysis(["market", "news"])
        buf.update_report_section("market_report", "Market data")
        buf.update_report_section("news_report", "News data")
        buf.update_report_section("investment_plan", "Research plan")
        buf.update_report_section("trader_investment_plan", "Trade plan")
        buf.update_report_section("final_trade_decision", "Final decision")
        assert buf.final_report is not None
        assert "Market Analysis" in buf.final_report
        assert "News Analysis" in buf.final_report
        assert "Research Team Decision" in buf.final_report
        assert "Trading Team Plan" in buf.final_report
        assert "Portfolio Management Decision" in buf.final_report

    def test_final_report_none_when_no_sections(self):
        buf = self._make()
        buf.init_for_analysis(["market"])
        assert buf.final_report is None


class TestFormatTokens:
    def test_under_1000(self):
        from cli.main import format_tokens
        assert format_tokens(500) == "500"

    def test_1000(self):
        from cli.main import format_tokens
        assert format_tokens(1000) == "1.0k"

    def test_millions(self):
        from cli.main import format_tokens
        assert format_tokens(1500000) == "1500.0k"


class TestCreateLayout:
    def test_returns_layout(self):
        from cli.main import create_layout
        from rich.layout import Layout
        layout = create_layout()
        assert isinstance(layout, Layout)


class TestExtractContentString:
    def _call(self, content):
        from cli.main import extract_content_string
        return extract_content_string(content)

    def test_none(self):
        assert self._call(None) is None

    def test_empty_string(self):
        assert self._call("") is None

    def test_whitespace_only(self):
        assert self._call("   ") is None

    def test_plain_string(self):
        assert self._call("hello world") == "hello world"

    def test_string_with_whitespace(self):
        assert self._call("  hello  ") == "hello"

    def test_dict_with_text(self):
        assert self._call({"text": "content"}) == "content"

    def test_dict_with_empty_text(self):
        assert self._call({"text": ""}) is None

    def test_list_of_text_items(self):
        items = [
            {"type": "text", "text": "hello"},
            {"type": "text", "text": "world"},
        ]
        assert self._call(items) == "hello world"

    def test_list_with_string(self):
        assert self._call(["hello", "world"]) == "hello world"

    def test_empty_list_string(self):
        assert self._call("[]") is None

    def test_non_parseable_string(self):
        assert self._call("just some text") == "just some text"

    def test_other_type(self):
        assert self._call(42) == "42"


class TestClassifyMessageType:
    def test_human_continue(self):
        from langchain_core.messages import HumanMessage
        from cli.main import classify_message_type
        typ, content = classify_message_type(HumanMessage(content="Continue"))
        assert typ == "Control"

    def test_human_regular(self):
        from langchain_core.messages import HumanMessage
        from cli.main import classify_message_type
        typ, content = classify_message_type(HumanMessage(content="Hello"))
        assert typ == "User"
        assert content == "Hello"

    def test_tool_message(self):
        from langchain_core.messages import ToolMessage
        from cli.main import classify_message_type
        typ, content = classify_message_type(ToolMessage(content="data", tool_call_id="t1"))
        assert typ == "Data"

    def test_ai_message(self):
        from langchain_core.messages import AIMessage
        from cli.main import classify_message_type
        typ, content = classify_message_type(AIMessage(content="analysis"))
        assert typ == "Agent"

    def test_unknown_type(self):
        from unittest.mock import MagicMock
        from cli.main import classify_message_type
        msg = MagicMock()
        msg.content = "test"
        typ, content = classify_message_type(msg)
        assert typ == "System"


class TestFormatToolArgs:
    def test_short(self):
        from cli.main import format_tool_args
        assert format_tool_args({"a": 1}) == "{'a': 1}"

    def test_truncated(self):
        from cli.main import format_tool_args
        long = "x" * 100
        result = format_tool_args(long, max_length=20)
        assert len(result) == 20
        assert result.endswith("...")


class TestUpdateAnalystStatuses:
    def test_sets_first_analyst_in_progress(self):
        from cli.main import MessageBuffer, update_analyst_statuses
        buf = MessageBuffer()
        buf.init_for_analysis(["market", "news"])
        chunk = {}
        update_analyst_statuses(buf, chunk)
        assert buf.agent_status["Market Analyst"] == "in_progress"
        assert buf.agent_status["News Analyst"] == "pending"

    def test_completed_when_report_present(self):
        from cli.main import MessageBuffer, update_analyst_statuses
        buf = MessageBuffer()
        buf.init_for_analysis(["market", "news"])
        chunk = {"market_report": "Analysis done"}
        update_analyst_statuses(buf, chunk)
        assert buf.agent_status["Market Analyst"] == "completed"
        assert buf.agent_status["News Analyst"] == "in_progress"

    def test_all_done_triggers_bull_researcher(self):
        from cli.main import MessageBuffer, update_analyst_statuses
        buf = MessageBuffer()
        buf.init_for_analysis(["market"])
        buf.report_sections["market_report"] = "done"
        buf.agent_status["Market Analyst"] = "completed"
        chunk = {}
        update_analyst_statuses(buf, chunk)
        assert buf.agent_status["Bull Researcher"] == "in_progress"
