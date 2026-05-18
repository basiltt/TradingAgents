# TradingAgents/graph/conditional_logic.py

from langchain_core.messages import AIMessage

from tradingagents.agents.utils.agent_states import AgentState


def _has_tool_calls(state: AgentState) -> bool:
    last = state["messages"][-1]
    return isinstance(last, AIMessage) and bool(last.tool_calls)


class ConditionalLogic:
    """Handles conditional logic for determining graph flow."""

    def __init__(self, max_debate_rounds: int = 1, max_risk_discuss_rounds: int = 1):
        """Initialize with configuration parameters."""
        self.max_debate_rounds = max_debate_rounds
        self.max_risk_discuss_rounds = max_risk_discuss_rounds

    def should_continue_market(self, state: AgentState) -> str:
        """Determine if market analysis should continue."""
        return "tools_market" if _has_tool_calls(state) else "Msg Clear Market"

    def should_continue_social(self, state: AgentState) -> str:
        """Determine if social media analysis should continue."""
        return "tools_social" if _has_tool_calls(state) else "Msg Clear Social"

    def should_continue_news(self, state: AgentState) -> str:
        """Determine if news analysis should continue."""
        return "tools_news" if _has_tool_calls(state) else "Msg Clear News"

    def should_continue_fundamentals(self, state: AgentState) -> str:
        """Determine if fundamentals analysis should continue."""
        return "tools_fundamentals" if _has_tool_calls(state) else "Msg Clear Fundamentals"

    def should_continue_crypto_technical(self, state: AgentState) -> str:
        return "tools_crypto_technical" if _has_tool_calls(state) else "Msg Clear Crypto_technical"

    def should_continue_crypto_derivatives(self, state: AgentState) -> str:
        return "tools_crypto_derivatives" if _has_tool_calls(state) else "Msg Clear Crypto_derivatives"

    def should_continue_crypto_news(self, state: AgentState) -> str:
        return "tools_crypto_news" if _has_tool_calls(state) else "Msg Clear Crypto_news"

    def should_continue_crypto_fundamentals(self, state: AgentState) -> str:
        return "tools_crypto_fundamentals" if _has_tool_calls(state) else "Msg Clear Crypto_fundamentals"

    def should_continue_crypto_social(self, state: AgentState) -> str:
        return "tools_crypto_social" if _has_tool_calls(state) else "Msg Clear Crypto_social"

    def should_continue_debate(self, state: AgentState) -> str:
        """Determine if debate should continue."""

        if (
            state["investment_debate_state"]["count"] >= 2 * self.max_debate_rounds
        ):  # 3 rounds of back-and-forth between 2 agents
            return "Research Manager"
        if state["investment_debate_state"]["current_response"].startswith("Bull"):
            return "Bear Researcher"
        return "Bull Researcher"

    def should_continue_risk_analysis(self, state: AgentState) -> str:
        """Determine if risk analysis should continue.

        Supports both 3-party (stock: Aggressive/Conservative/Neutral) and
        2-party (crypto: Bull/Bear) debate patterns.
        """
        count = state["risk_debate_state"]["count"]
        speaker = state["risk_debate_state"]["latest_speaker"]

        # 2-party crypto debate: bull/bear alternate
        if speaker.startswith("Bull") or speaker.startswith("Bear"):
            if count >= 2 * self.max_risk_discuss_rounds:
                return "Portfolio Manager"
            if speaker.startswith("Bull"):
                return "Bear Analyst"
            return "Bull Analyst"

        # 3-party stock debate
        if count >= 3 * self.max_risk_discuss_rounds:
            return "Portfolio Manager"
        if speaker.startswith("Aggressive"):
            return "Conservative Analyst"
        if speaker.startswith("Conservative"):
            return "Neutral Analyst"
        return "Aggressive Analyst"
