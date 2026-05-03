"""Stream parser — extracts domain events from LangGraph stream chunks — TASK-008."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterator, List, Optional, Union


class EventType(str, Enum):
    AGENT_STATUS = "agent_status"
    REPORT_CHUNK = "report_chunk"
    MESSAGE = "message"
    TOOL_CALL = "tool_call"
    STATS = "stats"
    PROGRESS = "progress"


@dataclass
class AgentStatusEvent:
    type: str = EventType.AGENT_STATUS
    agent: str = ""
    status: str = ""


@dataclass
class ReportChunkEvent:
    type: str = EventType.REPORT_CHUNK
    section: str = ""
    content: str = ""
    append: bool = True


@dataclass
class MessageEvent:
    type: str = EventType.MESSAGE
    sender: str = ""
    content: str = ""
    seq: int = 0


@dataclass
class ToolCallEvent:
    type: str = EventType.TOOL_CALL
    tool_name: str = ""
    args: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StatsEvent:
    type: str = EventType.STATS
    tokens_in: int = 0
    tokens_out: int = 0
    llm_calls: int = 0
    tool_calls: int = 0


@dataclass
class ProgressEvent:
    type: str = EventType.PROGRESS
    phase: str = ""
    detail: str = ""


DomainEvent = Union[
    AgentStatusEvent, ReportChunkEvent, MessageEvent,
    ToolCallEvent, StatsEvent, ProgressEvent
]

SECTION_KEYS = frozenset([
    "analyst_market", "analyst_social", "analyst_news", "analyst_fundamentals",
    "research_bull", "research_bear", "research_manager",
    "trader",
    "risk_aggressive", "risk_conservative", "risk_neutral",
    "portfolio_manager",
])

_DEBATE_FIELD_MAP = {
    "bull_history": ("research_bull", "Bull Researcher"),
    "bear_history": ("research_bear", "Bear Researcher"),
    "judge_decision": ("research_manager", "Research Manager"),
}

_RISK_FIELD_MAP = {
    "aggressive_history": ("risk_aggressive", "Aggressive Analyst"),
    "conservative_history": ("risk_conservative", "Conservative Analyst"),
    "neutral_history": ("risk_neutral", "Neutral Analyst"),
}

_ANALYST_REPORT_MAP = {
    "market_report": ("analyst_market", "Market Analyst"),
    "sentiment_report": ("analyst_social", "Social Analyst"),
    "news_report": ("analyst_news", "News Analyst"),
    "fundamentals_report": ("analyst_fundamentals", "Fundamentals Analyst"),
}


def make_seq_counter() -> Iterator[int]:
    return itertools.count(1)


class StreamParserState:
    """Tracks state across stream chunks to detect deltas (stream_mode=values)."""
    def __init__(self):
        self.msg_count = 0
        self.prev_debate: Optional[Dict] = None
        self.prev_risk: Optional[Dict] = None
        self.prev_trader: Optional[str] = None
        self.prev_final: Optional[str] = None
        self.prev_analyst_reports: Dict[str, str] = {}


def parse_stream_chunk(
    chunk: Dict[str, Any],
    seq: Optional[Iterator[int]] = None,
    state: Optional[StreamParserState] = None,
) -> List[DomainEvent]:
    events: List[DomainEvent] = []
    if state is None:
        state = StreamParserState()

    # Only process NEW messages (stream_mode=values sends full accumulated list)
    messages = chunk.get("messages", [])
    new_messages = messages[state.msg_count:] if isinstance(messages, list) else []
    state.msg_count = len(messages) if isinstance(messages, list) else state.msg_count

    for message in new_messages:
        content = getattr(message, "content", None) or ""
        if isinstance(content, str) and content.strip():
            sender = getattr(message, "name", None) or getattr(message, "type", "Unknown")
            seq_val = next(seq) if seq else 0
            events.append(MessageEvent(sender=str(sender), content=content.strip(), seq=seq_val))

        tool_calls = getattr(message, "tool_calls", None) or []
        for tc in tool_calls:
            if isinstance(tc, dict):
                events.append(ToolCallEvent(tool_name=tc.get("name", ""), args=tc.get("args", {})))
            else:
                events.append(ToolCallEvent(tool_name=getattr(tc, "name", ""), args=getattr(tc, "args", {})))

    # Detect current agent from the last new message
    if new_messages:
        last_msg = new_messages[-1]
        agent_name = getattr(last_msg, "name", None)
        if agent_name:
            events.insert(0, AgentStatusEvent(agent=agent_name, status="in_progress"))

    # Extract analyst reports (market, social, news, fundamentals)
    for field_name, (section, agent) in _ANALYST_REPORT_MAP.items():
        val = chunk.get(field_name)
        if isinstance(val, str) and val.strip():
            prev_val = state.prev_analyst_reports.get(field_name, "")
            if val.strip() != prev_val:
                events.append(AgentStatusEvent(agent=agent, status="completed"))
                events.append(ReportChunkEvent(section=section, content=val.strip()))
                state.prev_analyst_reports[field_name] = val.strip()

    debate = chunk.get("investment_debate_state")
    if debate and debate != state.prev_debate:
        for field_name, (section, agent) in _DEBATE_FIELD_MAP.items():
            val = debate.get(field_name, "").strip()
            prev_val = (state.prev_debate or {}).get(field_name, "").strip() if state.prev_debate else ""
            if val and val != prev_val:
                events.append(AgentStatusEvent(agent=agent, status="in_progress"))
                events.append(ReportChunkEvent(section=section, content=val))
        if debate.get("judge_decision", "").strip():
            events.append(AgentStatusEvent(agent="Research Manager", status="completed"))
            events.append(AgentStatusEvent(agent="Trader", status="in_progress"))
        state.prev_debate = debate

    trader_plan = chunk.get("trader_investment_plan")
    trader_str = str(trader_plan) if trader_plan else None
    if trader_str and trader_str != state.prev_trader:
        events.append(ReportChunkEvent(section="trader", content=trader_str))
        events.append(AgentStatusEvent(agent="Trader", status="completed"))
        state.prev_trader = trader_str

    risk = chunk.get("risk_debate_state")
    if risk and risk != state.prev_risk:
        for field_name, (section, agent) in _RISK_FIELD_MAP.items():
            val = risk.get(field_name, "").strip()
            prev_val = (state.prev_risk or {}).get(field_name, "").strip() if state.prev_risk else ""
            if val and val != prev_val:
                events.append(AgentStatusEvent(agent=agent, status="in_progress"))
                events.append(ReportChunkEvent(section=section, content=val))
        judge = risk.get("judge_decision", "").strip()
        prev_judge = (state.prev_risk or {}).get("judge_decision", "").strip() if state.prev_risk else ""
        if judge and judge != prev_judge:
            events.append(ReportChunkEvent(section="portfolio_manager", content=judge))
            for agent in ["Aggressive Analyst", "Conservative Analyst", "Neutral Analyst", "Portfolio Manager"]:
                events.append(AgentStatusEvent(agent=agent, status="completed"))
        state.prev_risk = risk

    final = chunk.get("final_trade_decision")
    final_str = str(final) if final else None
    if final_str and final_str != state.prev_final and not risk:
        events.append(ReportChunkEvent(section="portfolio_manager", content=final_str))
        state.prev_final = final_str

    return events
