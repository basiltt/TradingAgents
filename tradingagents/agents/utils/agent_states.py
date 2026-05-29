from typing import Annotated, Any, Optional
from typing_extensions import TypedDict
from langgraph.graph import MessagesState


def _last(existing, new):
    """Reducer that accepts concurrent writes by keeping the last value."""
    return new if new is not None else existing


# Researcher team state
class InvestDebateState(TypedDict):
    bull_history: Annotated[
        str, "Bullish Conversation history"
    ]  # Bullish Conversation history
    bear_history: Annotated[
        str, "Bearish Conversation history"
    ]  # Bullish Conversation history
    history: Annotated[str, "Conversation history"]  # Conversation history
    current_response: Annotated[str, "Latest response"]  # Last response
    judge_decision: Annotated[str, "Final judge decision"]  # Last response
    count: Annotated[int, "Length of the current conversation"]  # Conversation length


# Risk management team state
class RiskDebateState(TypedDict):
    aggressive_history: Annotated[
        str, "Aggressive Agent's Conversation history"
    ]  # Conversation history
    conservative_history: Annotated[
        str, "Conservative Agent's Conversation history"
    ]  # Conversation history
    neutral_history: Annotated[
        str, "Neutral Agent's Conversation history"
    ]  # Conversation history
    history: Annotated[str, "Conversation history"]  # Conversation history
    latest_speaker: Annotated[str, "Analyst that spoke last"]
    current_aggressive_response: Annotated[
        str, "Latest response by the aggressive analyst"
    ]  # Last response
    current_conservative_response: Annotated[
        str, "Latest response by the conservative analyst"
    ]  # Last response
    current_neutral_response: Annotated[
        str, "Latest response by the neutral analyst"
    ]  # Last response
    judge_decision: Annotated[str, "Judge's decision"]
    count: Annotated[int, "Length of the current conversation"]  # Conversation length


class AgentState(MessagesState):
    company_of_interest: Annotated[str, _last]
    trade_date: Annotated[str, _last]

    sender: Annotated[str, _last]

    # Asset type: "stock" or "crypto"
    asset_type: Annotated[str, _last]

    # User-selected kline interval for crypto analysis (e.g. "15", "60", "240", "D")
    crypto_interval: Annotated[Optional[str], _last]

    # Error propagation: set by analyst on critical failure, checked by downstream nodes
    error: Annotated[Optional[str], _last]

    # research step
    market_report: Annotated[str, _last]
    sentiment_report: Annotated[str, _last]
    news_report: Annotated[str, _last]
    fundamentals_report: Annotated[str, _last]  # deprecated alias — use derivatives_report
    derivatives_report: Annotated[str, _last]
    crypto_fundamentals_report: Annotated[str, _last]

    # researcher team discussion step
    investment_debate_state: Annotated[InvestDebateState, _last]
    investment_plan: Annotated[str, _last]

    trader_investment_plan: Annotated[str, _last]

    # risk management team discussion step
    risk_debate_state: Annotated[RiskDebateState, _last]
    final_trade_decision: Annotated[str, _last]
    past_context: Annotated[str, _last]
    current_price_context: Annotated[str, _last]
    confluence_summary: Annotated[str, _last]

    # Internal signal carriers — set by PM and Trader nodes, read by analysis_service.
    # Never written to logs, memory, or rendered markdown.
    _pm_signal_data: Annotated[Optional[Any], _last]
    _trader_signal_data: Annotated[Optional[Any], _last]

    # Compliance Officer result (pre-trade gate)
    compliance_result: Annotated[Optional[str], _last]
    _compliance_verdict: Annotated[Optional[str], _last]

    # Risk Manager
    risk_manager_result: Annotated[Optional[str], _last]
    _risk_manager_verdict: Annotated[Optional[str], _last]

    # Technical levels (bias-free) and market microstructure data
    technical_levels_summary: Annotated[Optional[str], _last]
    market_microstructure: Annotated[Optional[Any], _last]

    # Max leverage (moved from closure to state for barrier filtering)
    max_leverage: Annotated[Optional[int], _last]

    # Execution Monitor notes (post-decision addendum)
    execution_notes: Annotated[Optional[str], _last]

    # Trader context: market session
    market_session: Annotated[Optional[str], _last]

    # Historical signal performance feedback injected by the caller
    performance_context: Annotated[Optional[str], _last]
