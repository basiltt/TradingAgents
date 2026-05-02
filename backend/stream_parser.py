"""Stream parser — extracts domain events from LangGraph stream chunks — TASK-008."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union


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


def parse_stream_chunk(chunk: Dict[str, Any]) -> List[DomainEvent]:
    events: List[DomainEvent] = []

    for message in chunk.get("messages", []):
        content = getattr(message, "content", None) or ""
        if isinstance(content, str) and content.strip():
            sender = getattr(message, "name", None) or getattr(message, "type", "Unknown")
            events.append(MessageEvent(sender=str(sender), content=content.strip()))

        tool_calls = getattr(message, "tool_calls", None) or []
        for tc in tool_calls:
            if isinstance(tc, dict):
                events.append(ToolCallEvent(tool_name=tc.get("name", ""), args=tc.get("args", {})))
            else:
                events.append(ToolCallEvent(tool_name=getattr(tc, "name", ""), args=getattr(tc, "args", {})))

    debate = chunk.get("investment_debate_state")
    if debate:
        for field_name, (section, agent) in _DEBATE_FIELD_MAP.items():
            val = debate.get(field_name, "").strip()
            if val:
                events.append(AgentStatusEvent(agent=agent, status="in_progress"))
                events.append(ReportChunkEvent(section=section, content=val))
        if debate.get("judge_decision", "").strip():
            events.append(AgentStatusEvent(agent="Research Manager", status="completed"))
            events.append(AgentStatusEvent(agent="Trader", status="in_progress"))

    trader_plan = chunk.get("trader_investment_plan")
    if trader_plan:
        events.append(ReportChunkEvent(section="trader", content=str(trader_plan)))
        events.append(AgentStatusEvent(agent="Trader", status="completed"))

    risk = chunk.get("risk_debate_state")
    if risk:
        for field_name, (section, agent) in _RISK_FIELD_MAP.items():
            val = risk.get(field_name, "").strip()
            if val:
                events.append(AgentStatusEvent(agent=agent, status="in_progress"))
                events.append(ReportChunkEvent(section=section, content=val))
        judge = risk.get("judge_decision", "").strip()
        if judge:
            events.append(ReportChunkEvent(section="portfolio_manager", content=judge))
            for agent in ["Aggressive Analyst", "Conservative Analyst", "Neutral Analyst", "Portfolio Manager"]:
                events.append(AgentStatusEvent(agent=agent, status="completed"))

    final = chunk.get("final_trade_decision")
    if final and not risk:
        events.append(ReportChunkEvent(section="portfolio_manager", content=str(final)))

    return events
