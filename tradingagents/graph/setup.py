# TradingAgents/graph/setup.py

from typing import Any, Callable, Dict, List
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from tradingagents.agents import *
from tradingagents.agents.utils.agent_states import AgentState

from .conditional_logic import ConditionalLogic


def _compliance_router(state) -> str:
    """Route based on compliance verdict: fail-closed — only Pass/Flag proceed."""
    verdict = state.get("_compliance_verdict")
    if verdict in ("Pass", "Flag"):
        return "risk_debate"
    return "blocked"


def _blocked_trade_node(state) -> dict:
    """Terminal node for compliance-blocked trades. Writes a clear rejection."""
    compliance_result = state.get("compliance_result", "No details available.")
    return {
        "final_trade_decision": (
            "## TRADE BLOCKED BY COMPLIANCE\n\n"
            "This trade was blocked by the Compliance Officer and **must not be executed**.\n\n"
            f"### Compliance Review\n{compliance_result}"
        ),
    }


def _build_analyst_subgraph(
    analyst_type: str,
    analyst_node: Callable,
    tool_node: ToolNode,
    delete_node: Callable,
    should_continue_fn: Callable,
) -> Any:
    """Build a compiled subgraph for a single analyst's tool-call loop.

    The subgraph encapsulates: Analyst → [tools ↔ Analyst] → Msg Clear → END
    so the parent graph can fan out to multiple analysts in parallel.
    """
    sg = StateGraph(AgentState)
    sg.add_node("Analyst", analyst_node)
    sg.add_node("tools", tool_node)
    sg.add_node("Msg Clear", delete_node)

    sg.add_edge(START, "Analyst")
    sg.add_conditional_edges(
        "Analyst",
        should_continue_fn,
        {"tools": "tools", "Msg Clear": "Msg Clear"},
    )
    sg.add_edge("tools", "Analyst")
    sg.add_edge("Msg Clear", END)

    return sg.compile()


class GraphSetup:
    """Handles the setup and configuration of the agent graph."""

    def __init__(
        self,
        quick_thinking_llm: Any,
        deep_thinking_llm: Any,
        tool_nodes: Dict[str, ToolNode],
        conditional_logic: ConditionalLogic,
    ):
        """Initialize with required components."""
        self.quick_thinking_llm = quick_thinking_llm
        self.deep_thinking_llm = deep_thinking_llm
        self.tool_nodes = tool_nodes
        self.conditional_logic = conditional_logic

    def _analyst_should_continue(self, analyst_type: str) -> Callable:
        """Return a should_continue function adapted for the subgraph node names."""
        original_fn = getattr(self.conditional_logic, f"should_continue_{analyst_type}")

        def _wrapper(state: AgentState) -> str:
            result = original_fn(state)
            if result == f"tools_{analyst_type}":
                return "tools"
            return "Msg Clear"

        return _wrapper

    def setup_graph(
        self,
        selected_analysts=["market", "social", "news", "fundamentals"],
        compliance_officer_node=None,
        execution_monitor_node=None,
    ):
        """Set up and compile the agent workflow graph.

        Analysts run in parallel via compiled subgraphs, then fan-in
        to the Bull Researcher for the debate phase.
        """
        if len(selected_analysts) == 0:
            raise ValueError("Trading Agents Graph Setup Error: no analysts selected!")

        # Build analyst factory map
        analyst_factories = {
            "market": create_market_analyst,
            "social": create_social_media_analyst,
            "news": create_news_analyst,
            "fundamentals": create_fundamentals_analyst,
        }

        # Create researcher and manager nodes
        bull_researcher_node = create_bull_researcher(self.quick_thinking_llm)
        bear_researcher_node = create_bear_researcher(self.quick_thinking_llm)
        research_manager_node = create_research_manager(self.deep_thinking_llm)
        trader_node = create_trader(self.quick_thinking_llm)

        # Create risk analysis nodes
        aggressive_analyst = create_aggressive_debator(self.quick_thinking_llm)
        neutral_analyst = create_neutral_debator(self.quick_thinking_llm)
        conservative_analyst = create_conservative_debator(self.quick_thinking_llm)
        portfolio_manager_node = create_portfolio_manager(self.deep_thinking_llm)

        # Create workflow
        workflow = StateGraph(AgentState)

        # Add each analyst as a parallel subgraph node
        for analyst_type in selected_analysts:
            subgraph = _build_analyst_subgraph(
                analyst_type=analyst_type,
                analyst_node=analyst_factories[analyst_type](self.quick_thinking_llm),
                tool_node=self.tool_nodes[analyst_type],
                delete_node=create_msg_delete(),
                should_continue_fn=self._analyst_should_continue(analyst_type),
            )
            workflow.add_node(f"{analyst_type}_analysis", subgraph)
            workflow.add_edge(START, f"{analyst_type}_analysis")
            workflow.add_edge(f"{analyst_type}_analysis", "Bull Researcher")

        # Add other nodes
        workflow.add_node("Bull Researcher", bull_researcher_node)
        workflow.add_node("Bear Researcher", bear_researcher_node)
        workflow.add_node("Research Manager", research_manager_node)
        workflow.add_node("Trader", trader_node)
        workflow.add_node("Aggressive Analyst", aggressive_analyst)
        workflow.add_node("Neutral Analyst", neutral_analyst)
        workflow.add_node("Conservative Analyst", conservative_analyst)
        workflow.add_node("Portfolio Manager", portfolio_manager_node)

        # Add remaining edges
        workflow.add_conditional_edges(
            "Bull Researcher",
            self.conditional_logic.should_continue_debate,
            {
                "Bear Researcher": "Bear Researcher",
                "Research Manager": "Research Manager",
            },
        )
        workflow.add_conditional_edges(
            "Bear Researcher",
            self.conditional_logic.should_continue_debate,
            {
                "Bull Researcher": "Bull Researcher",
                "Research Manager": "Research Manager",
            },
        )
        workflow.add_edge("Research Manager", "Trader")

        # Compliance gate between Trader and Risk Analysts
        if compliance_officer_node:
            workflow.add_node("Compliance Officer", compliance_officer_node)
            workflow.add_node("Blocked Trade", _blocked_trade_node)
            workflow.add_edge("Trader", "Compliance Officer")
            workflow.add_conditional_edges(
                "Compliance Officer",
                _compliance_router,
                {
                    "risk_debate": "Aggressive Analyst",
                    "blocked": "Blocked Trade",
                },
            )
            workflow.add_edge("Blocked Trade", END)
        else:
            workflow.add_edge("Trader", "Aggressive Analyst")

        workflow.add_conditional_edges(
            "Aggressive Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Conservative Analyst": "Conservative Analyst",
                "Portfolio Manager": "Portfolio Manager",
            },
        )
        workflow.add_conditional_edges(
            "Conservative Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Neutral Analyst": "Neutral Analyst",
                "Portfolio Manager": "Portfolio Manager",
            },
        )
        workflow.add_conditional_edges(
            "Neutral Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Aggressive Analyst": "Aggressive Analyst",
                "Portfolio Manager": "Portfolio Manager",
            },
        )

        # Execution monitor after PM
        if execution_monitor_node:
            workflow.add_node("Execution Monitor", execution_monitor_node)
            workflow.add_edge("Portfolio Manager", "Execution Monitor")
            workflow.add_edge("Execution Monitor", END)
        else:
            workflow.add_edge("Portfolio Manager", END)

        return workflow

    def setup_crypto_graph(
        self,
        selected_analysts: List[str],
        crypto_analyst_nodes: Dict[str, Any],
        crypto_tool_nodes: Dict[str, ToolNode],
        crypto_trader_node: Any,
        crypto_bull_debater: Any,
        crypto_bear_debater: Any,
        crypto_portfolio_manager: Any,
        confluence_checker_node: Any = None,
        crypto_bull_researcher: Any = None,
        crypto_bear_researcher: Any = None,
        crypto_research_manager: Any = None,
        compliance_officer_node: Any = None,
        execution_monitor_node: Any = None,
    ):
        """Set up a crypto futures graph with bull/bear 2-party debate.

        Analysts run in parallel via compiled subgraphs, then fan-in to the
        next stage. When researchers + RM are provided, the flow is:
        Analysts → Confluence → Bull/Bear Researchers → RM → Trader → Risk Debate → PM
        """
        if not selected_analysts:
            raise ValueError("Trading Agents Graph Setup Error: no analysts selected!")

        has_research_layer = (
            crypto_bull_researcher is not None
            and crypto_bear_researcher is not None
            and crypto_research_manager is not None
        )

        # Fan-in target after analysts complete
        fan_in_target = "Confluence Checker" if confluence_checker_node else (
            "Bull Researcher" if has_research_layer else "Trader"
        )

        workflow = StateGraph(AgentState)

        # Add each analyst as a parallel subgraph node
        for analyst_type in selected_analysts:
            subgraph = _build_analyst_subgraph(
                analyst_type=analyst_type,
                analyst_node=crypto_analyst_nodes[analyst_type],
                tool_node=crypto_tool_nodes[analyst_type],
                delete_node=create_msg_delete(),
                should_continue_fn=self._analyst_should_continue(analyst_type),
            )
            workflow.add_node(f"{analyst_type}_analysis", subgraph)
            workflow.add_edge(START, f"{analyst_type}_analysis")
            workflow.add_edge(f"{analyst_type}_analysis", fan_in_target)

        if confluence_checker_node:
            workflow.add_node("Confluence Checker", confluence_checker_node)
            if has_research_layer:
                workflow.add_edge("Confluence Checker", "Bull Researcher")
            else:
                workflow.add_edge("Confluence Checker", "Trader")

        if has_research_layer:
            workflow.add_node("Bull Researcher", crypto_bull_researcher)
            workflow.add_node("Bear Researcher", crypto_bear_researcher)
            workflow.add_node("Research Manager", crypto_research_manager)

            workflow.add_conditional_edges(
                "Bull Researcher",
                self.conditional_logic.should_continue_debate,
                {
                    "Bear Researcher": "Bear Researcher",
                    "Research Manager": "Research Manager",
                },
            )
            workflow.add_conditional_edges(
                "Bear Researcher",
                self.conditional_logic.should_continue_debate,
                {
                    "Bull Researcher": "Bull Researcher",
                    "Research Manager": "Research Manager",
                },
            )
            workflow.add_edge("Research Manager", "Trader")

        workflow.add_node("Trader", crypto_trader_node)
        workflow.add_node("Bull Analyst", crypto_bull_debater)
        workflow.add_node("Bear Analyst", crypto_bear_debater)
        workflow.add_node("Portfolio Manager", crypto_portfolio_manager)

        # Compliance gate between Trader and Risk Debate
        if compliance_officer_node:
            workflow.add_node("Compliance Officer", compliance_officer_node)
            workflow.add_node("Blocked Trade", _blocked_trade_node)
            workflow.add_edge("Trader", "Compliance Officer")
            workflow.add_conditional_edges(
                "Compliance Officer",
                _compliance_router,
                {
                    "risk_debate": "Bull Analyst",
                    "blocked": "Blocked Trade",
                },
            )
            workflow.add_edge("Blocked Trade", END)
        else:
            workflow.add_edge("Trader", "Bull Analyst")

        workflow.add_conditional_edges(
            "Bull Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Bear Analyst": "Bear Analyst",
                "Portfolio Manager": "Portfolio Manager",
            },
        )
        workflow.add_conditional_edges(
            "Bear Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Bull Analyst": "Bull Analyst",
                "Portfolio Manager": "Portfolio Manager",
            },
        )
        # Execution monitor after PM
        if execution_monitor_node:
            workflow.add_node("Execution Monitor", execution_monitor_node)
            workflow.add_edge("Portfolio Manager", "Execution Monitor")
            workflow.add_edge("Execution Monitor", END)
        else:
            workflow.add_edge("Portfolio Manager", END)

        return workflow
