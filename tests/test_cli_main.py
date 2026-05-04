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
