"""Stream parser — extracts domain events from LangGraph stream chunks — TASK-008."""

from __future__ import annotations

import itertools
import json as _json
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
    "analyst_crypto_fundamentals",
    "research_bull", "research_bear", "research_manager",
    "trader",
    "risk_aggressive", "risk_conservative", "risk_neutral",
    "portfolio_manager",
    "compliance", "execution_monitor", "confluence",
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

_ANALYST_REPORT_MAP_STOCK = {
    "market_report": ("analyst_market", "Market Analyst"),
    "sentiment_report": ("analyst_social", "Social Analyst"),
    "news_report": ("analyst_news", "News Analyst"),
    "fundamentals_report": ("analyst_fundamentals", "Fundamentals Analyst"),
}

_ANALYST_REPORT_MAP_CRYPTO = {
    "market_report": ("analyst_crypto_technical", "Technical Analyst"),
    "derivatives_report": ("analyst_crypto_derivatives", "Derivatives Analyst"),
    "fundamentals_report": ("analyst_crypto_derivatives", "Derivatives Analyst"),  # migration compat
    "news_report": ("analyst_crypto_news", "News Analyst"),
    "crypto_fundamentals_report": ("analyst_crypto_fundamentals", "Fundamentals Analyst"),
    "sentiment_report": ("analyst_crypto_social", "Social Analyst"),
}

_ANALYST_REPORT_MAP = _ANALYST_REPORT_MAP_STOCK


def make_seq_counter() -> Iterator[int]:
    return itertools.count(1)


class StreamParserState:
    """Tracks state across stream chunks to detect deltas (stream_mode=values)."""
    def __init__(self, workflow_mode: str = "deep_analysis", asset_type: str = "stock"):
        self.workflow_mode = workflow_mode
        self.asset_type = asset_type
        self.msg_count = 0
        self.prev_debate: Optional[Dict] = None
        self.prev_risk: Optional[Dict] = None
        self.prev_trader: Optional[str] = None
        self.prev_final: Optional[str] = None
        self.prev_analyst_reports: Dict[str, str] = {}
        self.prev_compliance: Optional[str] = None
        self.prev_risk_manager: Optional[str] = None
        self.prev_execution_notes: Optional[str] = None
        self.prev_confluence: Optional[str] = None
        self.seen_in_progress: set = set()

    def _ensure_in_progress(self, events: List, agent: str) -> None:
        """Emit an in_progress event before completed if this agent hasn't been seen running."""
        if agent not in self.seen_in_progress:
            events.append(AgentStatusEvent(agent=agent, status="in_progress"))
        self.seen_in_progress.add(agent)

    def mark_in_progress(self, agent: str) -> None:
        self.seen_in_progress.add(agent)


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
    report_map = _ANALYST_REPORT_MAP_CRYPTO if state.asset_type == "crypto" else _ANALYST_REPORT_MAP_STOCK
    for field_name, (section, agent) in report_map.items():
        val = chunk.get(field_name)
        if isinstance(val, str) and val.strip():
            prev_val = state.prev_analyst_reports.get(field_name, "")
            if val.strip() != prev_val:
                state._ensure_in_progress(events, agent)
                events.append(AgentStatusEvent(agent=agent, status="completed"))
                events.append(ReportChunkEvent(section=section, content=val.strip(), append=False))
                state.prev_analyst_reports[field_name] = val.strip()

    debate = chunk.get("investment_debate_state")
    if debate and debate != state.prev_debate:
        for field_name, (section, agent) in _DEBATE_FIELD_MAP.items():
            val = debate.get(field_name, "").strip()
            prev_val = (state.prev_debate or {}).get(field_name, "").strip() if state.prev_debate else ""
            if val and val != prev_val:
                state.mark_in_progress(agent)
                events.append(AgentStatusEvent(agent=agent, status="in_progress"))
                events.append(ReportChunkEvent(section=section, content=val))
        if debate.get("judge_decision", "").strip():
            prev_judge = (state.prev_debate or {}).get("judge_decision", "").strip() if state.prev_debate else ""
            if debate["judge_decision"].strip() != prev_judge:
                state._ensure_in_progress(events, "Bull Researcher")
                events.append(AgentStatusEvent(agent="Bull Researcher", status="completed"))
                state._ensure_in_progress(events, "Bear Researcher")
                events.append(AgentStatusEvent(agent="Bear Researcher", status="completed"))
                state._ensure_in_progress(events, "Research Manager")
                events.append(AgentStatusEvent(agent="Research Manager", status="completed"))
                events.append(AgentStatusEvent(agent="Trader", status="in_progress"))
                state.mark_in_progress("Trader")
        state.prev_debate = debate

    trader_plan = chunk.get("trader_investment_plan")
    if trader_plan is not None:
        if isinstance(trader_plan, dict):
            trader_str = _json.dumps(trader_plan, sort_keys=True)
        elif isinstance(trader_plan, str) and trader_plan.strip():
            # Normalize: parse then re-serialize so dedup comparison is stable
            try:
                trader_str = _json.dumps(_json.loads(trader_plan.strip()), sort_keys=True)
            except (_json.JSONDecodeError, ValueError):
                trader_str = trader_plan.strip()
        else:
            trader_str = None
    else:
        trader_str = None
    if trader_str and trader_str != state.prev_trader:
        events.append(ReportChunkEvent(section="trader", content=trader_str, append=False))
        state._ensure_in_progress(events, "Trader")
        events.append(AgentStatusEvent(agent="Trader", status="completed"))
        if state.workflow_mode == "quick_trade":
            events.append(AgentStatusEvent(agent="Risk Manager", status="in_progress"))
            state.mark_in_progress("Risk Manager")
        else:
            events.append(AgentStatusEvent(agent="Compliance Officer", status="in_progress"))
            state.mark_in_progress("Compliance Officer")
        state.prev_trader = trader_str

    # Compliance Officer result
    compliance_val = chunk.get("compliance_result")
    if isinstance(compliance_val, str) and compliance_val.strip():
        if compliance_val.strip() != state.prev_compliance:
            state._ensure_in_progress(events, "Compliance Officer")
            events.append(AgentStatusEvent(agent="Compliance Officer", status="completed"))
            events.append(ReportChunkEvent(section="compliance", content=compliance_val.strip(), append=False))
            state.prev_compliance = compliance_val.strip()

    # Risk Manager result
    risk_mgr_val = chunk.get("risk_manager_result")
    if isinstance(risk_mgr_val, str) and risk_mgr_val.strip():
        if risk_mgr_val.strip() != state.prev_risk_manager:
            state._ensure_in_progress(events, "Risk Manager")
            events.append(AgentStatusEvent(agent="Risk Manager", status="completed"))
            events.append(ReportChunkEvent(section="risk_manager", content=risk_mgr_val.strip(), append=False))
            state.prev_risk_manager = risk_mgr_val.strip()

    # Confluence summary
    confluence_val = chunk.get("confluence_summary")
    if isinstance(confluence_val, str) and confluence_val.strip():
        if confluence_val.strip() != state.prev_confluence:
            state._ensure_in_progress(events, "Confluence Checker")
            events.append(AgentStatusEvent(agent="Confluence Checker", status="completed"))
            events.append(ReportChunkEvent(section="confluence", content=confluence_val.strip(), append=False))
            events.append(AgentStatusEvent(agent="Bull Researcher", status="in_progress"))
            state.mark_in_progress("Bull Researcher")
            events.append(AgentStatusEvent(agent="Bear Researcher", status="in_progress"))
            state.mark_in_progress("Bear Researcher")
            state.prev_confluence = confluence_val.strip()

    risk = chunk.get("risk_debate_state")
    if risk and risk != state.prev_risk and state.workflow_mode != "quick_trade":
        for field_name, (section, agent) in _RISK_FIELD_MAP.items():
            val = risk.get(field_name, "").strip()
            prev_val = (state.prev_risk or {}).get(field_name, "").strip() if state.prev_risk else ""
            if val and val != prev_val:
                state.mark_in_progress(agent)
                events.append(AgentStatusEvent(agent=agent, status="in_progress"))
                events.append(ReportChunkEvent(section=section, content=val))
        judge = risk.get("judge_decision", "").strip()
        prev_judge = (state.prev_risk or {}).get("judge_decision", "").strip() if state.prev_risk else ""
        if judge and judge != prev_judge:
            events.append(ReportChunkEvent(section="portfolio_manager", content=judge, append=False))
            for agent in [
                "Aggressive Analyst", "Conservative Analyst", "Neutral Analyst",
                "Bull Analyst", "Bear Analyst",
            ]:
                state._ensure_in_progress(events, agent)
                events.append(AgentStatusEvent(agent=agent, status="completed"))
            events.append(AgentStatusEvent(agent="Portfolio Manager", status="in_progress"))
            state.mark_in_progress("Portfolio Manager")
        state.prev_risk = risk

    final = chunk.get("final_trade_decision")
    if isinstance(final, dict):
        final_str = _json.dumps(final, sort_keys=True)
    elif isinstance(final, str) and final.strip():
        try:
            final_str = _json.dumps(_json.loads(final.strip()), sort_keys=True)
        except (_json.JSONDecodeError, ValueError):
            final_str = final.strip()
    else:
        final_str = None
    if final_str and final_str != state.prev_final and not risk:
        if state.workflow_mode != "quick_trade":
            events.append(ReportChunkEvent(section="portfolio_manager", content=final_str, append=False))
            state._ensure_in_progress(events, "Portfolio Manager")
            events.append(AgentStatusEvent(agent="Portfolio Manager", status="completed"))
            events.append(AgentStatusEvent(agent="Execution Monitor", status="in_progress"))
            state.mark_in_progress("Execution Monitor")
        else:
            events.append(ReportChunkEvent(section="final_decision", content=final_str, append=False))
        state.prev_final = final_str

    # Execution Monitor notes
    exec_notes = chunk.get("execution_notes")
    if isinstance(exec_notes, str) and exec_notes.strip():
        if exec_notes.strip() != state.prev_execution_notes:
            state._ensure_in_progress(events, "Execution Monitor")
            events.append(AgentStatusEvent(agent="Execution Monitor", status="completed"))
            events.append(ReportChunkEvent(section="execution_monitor", content=exec_notes.strip(), append=False))
            state.prev_execution_notes = exec_notes.strip()

    return events
