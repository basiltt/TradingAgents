# TradingAgents/graph/propagation.py

from typing import Dict, Any, List, Optional
from tradingagents.agents.utils.agent_states import (
    InvestDebateState,
    RiskDebateState,
)


class Propagator:
    """Handles state initialization and propagation through the graph."""

    def __init__(self, max_recur_limit=100):
        """Initialize with configuration parameters."""
        self.max_recur_limit = max_recur_limit

    def create_initial_state(
        self, company_name: str, trade_date: str, past_context: str = "",
        asset_type: str = "stock", crypto_interval: str | None = None,
        performance_context: str = "", regime_context: str = "",
    ) -> Dict[str, Any]:
        """Create the initial state for the agent graph."""
        return {
            "messages": [("human", company_name)],
            "company_of_interest": company_name,
            "trade_date": str(trade_date),
            "past_context": past_context,
            "performance_context": performance_context,
            "regime_context": regime_context,
            "asset_type": asset_type,
            "crypto_interval": crypto_interval,
            "error": None,
            "investment_debate_state": InvestDebateState(
                {
                    "bull_history": "",
                    "bear_history": "",
                    "history": "",
                    "current_response": "",
                    "judge_decision": "",
                    "count": 0,
                }
            ),
            "risk_debate_state": RiskDebateState(
                {
                    "aggressive_history": "",
                    "conservative_history": "",
                    "neutral_history": "",
                    "history": "",
                    "latest_speaker": "",
                    "current_aggressive_response": "",
                    "current_conservative_response": "",
                    "current_neutral_response": "",
                    "judge_decision": "",
                    "count": 0,
                }
            ),
            "market_report": "",
            "fundamentals_report": "",
            "derivatives_report": "",
            "sentiment_report": "",
            "news_report": "",
            "current_price_context": "",
            "confluence_summary": "",
            "crypto_fundamentals_report": "",
            "risk_manager_result": "",
            "_risk_manager_verdict": "",
            "_compliance_verdict": "",
            "compliance_result": "",
            "execution_notes": "",
            "_pm_signal_data": None,
            "_trader_signal_data": None,
            "technical_levels_summary": "",
            "market_microstructure": None,
            "max_leverage": None,
        }

    def get_graph_args(self, callbacks: Optional[List] = None) -> Dict[str, Any]:
        """Get arguments for the graph invocation.

        Args:
            callbacks: Optional list of callback handlers for tool execution tracking.
                       Note: LLM callbacks are handled separately via LLM constructor.
        """
        config = {"recursion_limit": self.max_recur_limit}
        if callbacks:
            config["callbacks"] = callbacks
        return {
            "stream_mode": "values",
            "config": config,
        }
