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
    # 3 stock risk analysts + 2 crypto risk analysts = 5 completed
    assert len(completed) == 5
    completed_names = {e.agent for e in completed}
    assert "Aggressive Analyst" in completed_names
    assert "Conservative Analyst" in completed_names
    assert "Neutral Analyst" in completed_names
    assert "Bull Analyst" in completed_names
    assert "Bear Analyst" in completed_names
    # PM should be in_progress, not completed (completed when final_trade_decision arrives)
    pm_events = [e for e in events if isinstance(e, AgentStatusEvent) and e.agent == "Portfolio Manager"]
    assert any(e.status == "in_progress" for e in pm_events)


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


def test_analyst_report_emits_events():
    from backend.stream_parser import parse_stream_chunk, AgentStatusEvent, ReportChunkEvent

    chunk = {"market_report": "Market analysis data"}
    events = parse_stream_chunk(chunk)
    assert any(isinstance(e, AgentStatusEvent) and e.agent == "Market Analyst" and e.status == "completed" for e in events)
    assert any(isinstance(e, ReportChunkEvent) and e.section == "analyst_market" for e in events)


def test_analyst_report_dedup_with_state():
    from backend.stream_parser import parse_stream_chunk, StreamParserState, ReportChunkEvent

    state = StreamParserState()
    chunk = {"sentiment_report": "Social data"}
    events1 = parse_stream_chunk(chunk, state=state)
    events2 = parse_stream_chunk(chunk, state=state)
    assert any(isinstance(e, ReportChunkEvent) for e in events1)
    assert not any(isinstance(e, ReportChunkEvent) for e in events2)


def test_final_trade_decision_without_risk():
    from backend.stream_parser import parse_stream_chunk, ReportChunkEvent

    chunk = {"final_trade_decision": "Buy AAPL"}
    events = parse_stream_chunk(chunk)
    assert any(isinstance(e, ReportChunkEvent) and e.section == "portfolio_manager" for e in events)


def test_final_trade_decision_with_risk_is_skipped():
    from backend.stream_parser import parse_stream_chunk, ReportChunkEvent

    chunk = {
        "final_trade_decision": "Buy AAPL",
        "risk_debate_state": {"aggressive_history": "Go", "conservative_history": "", "neutral_history": "", "judge_decision": ""},
    }
    events = parse_stream_chunk(chunk)
    # final_trade_decision should be skipped when risk is present
    final_events = [e for e in events if isinstance(e, ReportChunkEvent) and e.section == "portfolio_manager"]
    assert len(final_events) == 0


def test_non_dict_tool_call():
    from backend.stream_parser import parse_stream_chunk, ToolCallEvent

    tc = MagicMock()
    tc.name = "my_tool"
    tc.args = {"key": "val"}

    msg = MagicMock()
    msg.content = ""
    msg.name = "Agent"
    msg.tool_calls = [tc]

    events = parse_stream_chunk({"messages": [msg]})
    assert any(isinstance(e, ToolCallEvent) and e.tool_name == "my_tool" for e in events)


def test_seq_counter():
    from backend.stream_parser import parse_stream_chunk, make_seq_counter, MessageEvent

    seq = make_seq_counter()
    msg1 = MagicMock()
    msg1.content = "First"
    msg1.name = "Agent"
    msg1.tool_calls = []
    msg2 = MagicMock()
    msg2.content = "Second"
    msg2.name = "Agent"
    msg2.tool_calls = []

    events = parse_stream_chunk({"messages": [msg1, msg2]}, seq=seq)
    msg_events = [e for e in events if isinstance(e, MessageEvent)]
    assert msg_events[0].seq == 1
    assert msg_events[1].seq == 2


def test_debate_chunk_with_judge_decision():
    """Covers stream_parser.py:170-171: judge_decision branch."""
    from backend.stream_parser import parse_stream_chunk, make_seq_counter, StreamParserState, AgentStatusEvent

    seq = make_seq_counter()
    state = StreamParserState()
    chunk = {
        "investment_debate_state": {
            "bull_researcher_report": "Bullish",
            "judge_decision": "BUY",
        }
    }
    events = parse_stream_chunk(chunk, seq=seq, state=state)
    agent_events = [e for e in events if isinstance(e, AgentStatusEvent)]
    agents = [e.agent for e in agent_events]
    assert "Research Manager" in agents
    assert "Trader" in agents


def test_in_progress_emitted_before_completed_for_analysts():
    """Every agent gets an in_progress event before completed."""
    from backend.stream_parser import parse_stream_chunk, StreamParserState, AgentStatusEvent

    state = StreamParserState()
    chunk = {"market_report": "Analysis data"}
    events = parse_stream_chunk(chunk, state=state)

    agent_events = [e for e in events if isinstance(e, AgentStatusEvent) and e.agent == "Market Analyst"]
    statuses = [e.status for e in agent_events]
    assert statuses == ["in_progress", "completed"]


def test_in_progress_emitted_before_completed_for_confluence():
    from backend.stream_parser import parse_stream_chunk, StreamParserState, AgentStatusEvent

    state = StreamParserState()
    chunk = {"confluence_summary": "Summary data"}
    events = parse_stream_chunk(chunk, state=state)

    cc_events = [e for e in events if isinstance(e, AgentStatusEvent) and e.agent == "Confluence Checker"]
    statuses = [e.status for e in cc_events]
    assert statuses == ["in_progress", "completed"]


def test_in_progress_not_duplicated_on_second_chunk():
    """If agent was already seen in_progress, don't emit in_progress again before completed."""
    from backend.stream_parser import parse_stream_chunk, StreamParserState, AgentStatusEvent

    state = StreamParserState()
    state.seen_in_progress.add("Compliance Officer")

    chunk = {"compliance_result": "Pass"}
    events = parse_stream_chunk(chunk, state=state)

    co_events = [e for e in events if isinstance(e, AgentStatusEvent) and e.agent == "Compliance Officer"]
    statuses = [e.status for e in co_events]
    assert statuses == ["completed"]


def test_quick_trade_skips_compliance_on_trader_complete():
    """In quick_trade mode, Trader completion should NOT emit Compliance Officer in_progress."""
    from backend.stream_parser import parse_stream_chunk, StreamParserState, AgentStatusEvent

    state = StreamParserState(workflow_mode="quick_trade")
    chunk = {"trader_investment_plan": "Buy SPY"}
    events = parse_stream_chunk(chunk, state=state)

    assert any(isinstance(e, AgentStatusEvent) and e.agent == "Trader" and e.status == "completed" for e in events)
    assert not any(isinstance(e, AgentStatusEvent) and e.agent == "Compliance Officer" for e in events)


def test_deep_analysis_emits_compliance_on_trader_complete():
    """In deep_analysis mode, Trader completion should emit Compliance Officer in_progress."""
    from backend.stream_parser import parse_stream_chunk, StreamParserState, AgentStatusEvent

    state = StreamParserState(workflow_mode="deep_analysis")
    chunk = {"trader_investment_plan": "Buy SPY"}
    events = parse_stream_chunk(chunk, state=state)

    assert any(isinstance(e, AgentStatusEvent) and e.agent == "Trader" and e.status == "completed" for e in events)
    assert any(isinstance(e, AgentStatusEvent) and e.agent == "Compliance Officer" and e.status == "in_progress" for e in events)


def test_quick_trade_skips_pm_and_exec_monitor_on_final_decision():
    """In quick_trade mode, final_trade_decision should NOT emit PM/Execution Monitor events but SHOULD emit report."""
    from backend.stream_parser import parse_stream_chunk, StreamParserState, AgentStatusEvent, ReportChunkEvent

    state = StreamParserState(workflow_mode="quick_trade")
    chunk = {"final_trade_decision": "Buy AAPL"}
    events = parse_stream_chunk(chunk, state=state)

    assert not any(isinstance(e, AgentStatusEvent) and e.agent == "Portfolio Manager" for e in events)
    assert not any(isinstance(e, AgentStatusEvent) and e.agent == "Execution Monitor" for e in events)
    assert not any(isinstance(e, ReportChunkEvent) and e.section == "portfolio_manager" for e in events)
    assert any(isinstance(e, ReportChunkEvent) and e.section == "final_decision" for e in events)


def test_quick_trade_trader_emits_risk_manager_in_progress():
    """In quick_trade mode, Trader completion should emit Risk Manager in_progress."""
    from backend.stream_parser import parse_stream_chunk, StreamParserState, AgentStatusEvent

    state = StreamParserState(workflow_mode="quick_trade")
    chunk = {"trader_investment_plan": "Buy BTC at 100k"}
    events = parse_stream_chunk(chunk, state=state)

    assert any(
        isinstance(e, AgentStatusEvent) and e.agent == "Risk Manager" and e.status == "in_progress"
        for e in events
    )
    assert not any(
        isinstance(e, AgentStatusEvent) and e.agent == "Compliance Officer"
        for e in events
    )


def test_risk_manager_result_emits_events():
    """Risk Manager result should emit completed status and report chunk."""
    from backend.stream_parser import parse_stream_chunk, StreamParserState, AgentStatusEvent, ReportChunkEvent

    state = StreamParserState(workflow_mode="quick_trade")
    chunk = {"risk_manager_result": "Approved. Risk score: 25/100."}
    events = parse_stream_chunk(chunk, state=state)

    assert any(
        isinstance(e, AgentStatusEvent) and e.agent == "Risk Manager" and e.status == "completed"
        for e in events
    )
    assert any(
        isinstance(e, ReportChunkEvent) and e.section == "risk_manager"
        for e in events
    )


def test_risk_manager_result_dedup():
    """Duplicate risk_manager_result should not emit events twice."""
    from backend.stream_parser import parse_stream_chunk, StreamParserState, AgentStatusEvent

    state = StreamParserState(workflow_mode="quick_trade")
    chunk = {"risk_manager_result": "Approved."}
    parse_stream_chunk(chunk, state=state)

    events2 = parse_stream_chunk(chunk, state=state)
    assert not any(
        isinstance(e, AgentStatusEvent) and e.agent == "Risk Manager"
        for e in events2
    )


def test_quick_trade_skips_risk_debate_events():
    """In quick_trade mode, risk_debate_state changes should NOT emit risk debate agent events."""
    from backend.stream_parser import parse_stream_chunk, StreamParserState, AgentStatusEvent

    state = StreamParserState(workflow_mode="quick_trade")
    chunk = {
        "risk_debate_state": {
            "current_aggressive_response": "Go big!",
            "current_conservative_response": "Be careful",
            "current_neutral_response": "Balanced view",
            "judge_decision": "",
            "aggressive_history": "",
            "conservative_history": "",
            "neutral_history": "",
            "history": "",
            "latest_speaker": "",
            "count": 0,
        }
    }
    events = parse_stream_chunk(chunk, state=state)

    assert not any(
        isinstance(e, AgentStatusEvent) and e.agent in (
            "Aggressive Analyst", "Conservative Analyst", "Neutral Analyst",
            "Bull Analyst", "Bear Analyst", "Portfolio Manager",
        )
        for e in events
    )
