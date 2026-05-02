"""Tests for stream parser — TASK-008."""

from unittest.mock import MagicMock


def test_parse_message_event():
    from backend.stream_parser import parse_stream_chunk, MessageEvent

    msg = MagicMock()
    msg.content = "Market analysis complete"
    msg.name = "MarketAnalyst"
    msg.tool_calls = []

    events = parse_stream_chunk({"messages": [msg]})
    assert any(isinstance(e, MessageEvent) and e.sender == "MarketAnalyst" for e in events)


def test_parse_tool_call_event():
    from backend.stream_parser import parse_stream_chunk, ToolCallEvent

    msg = MagicMock()
    msg.content = ""
    msg.name = "Agent"
    msg.tool_calls = [{"name": "get_stock_data", "args": {"ticker": "SPY"}}]

    events = parse_stream_chunk({"messages": [msg]})
    assert any(isinstance(e, ToolCallEvent) and e.tool_name == "get_stock_data" for e in events)


def test_parse_debate_state():
    from backend.stream_parser import parse_stream_chunk, AgentStatusEvent, ReportChunkEvent

    chunk = {
        "investment_debate_state": {
            "bull_history": "Bullish outlook",
            "bear_history": "",
            "judge_decision": "",
        }
    }
    events = parse_stream_chunk(chunk)
    assert any(isinstance(e, AgentStatusEvent) and e.agent == "Bull Researcher" for e in events)
    assert any(isinstance(e, ReportChunkEvent) and e.section == "research_bull" for e in events)


def test_parse_trader_plan():
    from backend.stream_parser import parse_stream_chunk, ReportChunkEvent, AgentStatusEvent

    chunk = {"trader_investment_plan": "Buy SPY at market open"}
    events = parse_stream_chunk(chunk)
    assert any(isinstance(e, ReportChunkEvent) and e.section == "trader" for e in events)
    assert any(isinstance(e, AgentStatusEvent) and e.agent == "Trader" and e.status == "completed" for e in events)


def test_parse_risk_debate():
    from backend.stream_parser import parse_stream_chunk, AgentStatusEvent

    chunk = {
        "risk_debate_state": {
            "aggressive_history": "Go all in",
            "conservative_history": "Be cautious",
            "neutral_history": "Balanced approach",
            "judge_decision": "Final portfolio decision",
        }
    }
    events = parse_stream_chunk(chunk)
    completed = [e for e in events if isinstance(e, AgentStatusEvent) and e.status == "completed"]
    assert len(completed) == 4


def test_unknown_chunk_skipped():
    from backend.stream_parser import parse_stream_chunk

    events = parse_stream_chunk({"unknown_key": "some value"})
    assert events == []


def test_malformed_message_handled():
    from backend.stream_parser import parse_stream_chunk

    msg = MagicMock()
    msg.content = None
    msg.name = None
    msg.type = "ai"
    msg.tool_calls = None

    events = parse_stream_chunk({"messages": [msg]})
    assert isinstance(events, list)
