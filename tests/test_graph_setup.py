"""Tests for tradingagents.graph.setup — Phase 1 unit tests."""

from unittest.mock import MagicMock, patch
import pytest


def _make_setup(conditional_logic=None):
    from tradingagents.graph.setup import GraphSetup
    from tradingagents.graph.conditional_logic import ConditionalLogic
    cl = conditional_logic or ConditionalLogic()
    tool_nodes = {
        "market": MagicMock(),
        "social": MagicMock(),
        "news": MagicMock(),
        "fundamentals": MagicMock(),
    }
    return GraphSetup(
        quick_thinking_llm=MagicMock(),
        deep_thinking_llm=MagicMock(),
        tool_nodes=tool_nodes,
        conditional_logic=cl,
    )


class TestSetupGraph:
    def test_empty_analysts_raises(self):
        gs = _make_setup()
        with pytest.raises(ValueError, match="no analysts selected"):
            gs.setup_graph(selected_analysts=[])

    @patch("tradingagents.graph.setup.create_market_analyst", return_value=MagicMock())
    @patch("tradingagents.graph.setup.create_social_media_analyst", return_value=MagicMock())
    @patch("tradingagents.graph.setup.create_news_analyst", return_value=MagicMock())
    @patch("tradingagents.graph.setup.create_fundamentals_analyst", return_value=MagicMock())
    @patch("tradingagents.graph.setup.create_bull_researcher", return_value=MagicMock())
    @patch("tradingagents.graph.setup.create_bear_researcher", return_value=MagicMock())
    @patch("tradingagents.graph.setup.create_research_manager", return_value=MagicMock())
    @patch("tradingagents.graph.setup.create_trader", return_value=MagicMock())
    @patch("tradingagents.graph.setup.create_aggressive_debator", return_value=MagicMock())
    @patch("tradingagents.graph.setup.create_neutral_debator", return_value=MagicMock())
    @patch("tradingagents.graph.setup.create_conservative_debator", return_value=MagicMock())
    @patch("tradingagents.graph.setup.create_portfolio_manager", return_value=MagicMock())
    @patch("tradingagents.graph.setup.create_msg_delete", return_value=MagicMock())
    def test_all_analysts(self, *mocks):
        gs = _make_setup()
        workflow = gs.setup_graph(["market", "social", "news", "fundamentals"])
        assert workflow is not None

    @patch("tradingagents.graph.setup.create_market_analyst", return_value=MagicMock())
    @patch("tradingagents.graph.setup.create_bull_researcher", return_value=MagicMock())
    @patch("tradingagents.graph.setup.create_bear_researcher", return_value=MagicMock())
    @patch("tradingagents.graph.setup.create_research_manager", return_value=MagicMock())
    @patch("tradingagents.graph.setup.create_trader", return_value=MagicMock())
    @patch("tradingagents.graph.setup.create_aggressive_debator", return_value=MagicMock())
    @patch("tradingagents.graph.setup.create_neutral_debator", return_value=MagicMock())
    @patch("tradingagents.graph.setup.create_conservative_debator", return_value=MagicMock())
    @patch("tradingagents.graph.setup.create_portfolio_manager", return_value=MagicMock())
    @patch("tradingagents.graph.setup.create_msg_delete", return_value=MagicMock())
    def test_single_analyst(self, *mocks):
        gs = _make_setup()
        workflow = gs.setup_graph(["market"])
        assert workflow is not None


class TestSetupCryptoGraph:
    def test_empty_analysts_raises(self):
        gs = _make_setup()
        with pytest.raises(ValueError, match="no analysts selected"):
            gs.setup_crypto_graph(
                selected_analysts=[],
                crypto_analyst_nodes={},
                crypto_tool_nodes={},
                crypto_trader_node=MagicMock(),
                crypto_bull_debater=MagicMock(),
                crypto_bear_debater=MagicMock(),
                crypto_portfolio_manager=MagicMock(),
            )

    @patch("tradingagents.graph.setup.create_msg_delete", return_value=MagicMock())
    def test_crypto_graph_builds(self, mock_delete):
        gs = _make_setup()
        workflow = gs.setup_crypto_graph(
            selected_analysts=["crypto_technical", "crypto_news"],
            crypto_analyst_nodes={
                "crypto_technical": MagicMock(),
                "crypto_news": MagicMock(),
            },
            crypto_tool_nodes={
                "crypto_technical": MagicMock(),
                "crypto_news": MagicMock(),
            },
            crypto_trader_node=MagicMock(),
            crypto_bull_debater=MagicMock(),
            crypto_bear_debater=MagicMock(),
            crypto_portfolio_manager=MagicMock(),
        )
        assert workflow is not None


class TestQuickTradeGraph:
    """Verify quick_trade graph compilation and node sets."""

    @patch("tradingagents.graph.setup.create_market_analyst", return_value=MagicMock())
    @patch("tradingagents.graph.setup.create_bull_researcher", return_value=MagicMock())
    @patch("tradingagents.graph.setup.create_bear_researcher", return_value=MagicMock())
    @patch("tradingagents.graph.setup.create_research_manager", return_value=MagicMock())
    @patch("tradingagents.graph.setup.create_trader", return_value=MagicMock())
    @patch("tradingagents.graph.setup.create_msg_delete", return_value=MagicMock())
    def test_stock_quick_trade_compiles(self, *mocks):
        gs = _make_setup()
        workflow = gs.setup_graph(["market"], workflow_mode="quick_trade")
        graph = workflow.compile()
        node_names = set(graph.get_graph().nodes.keys())
        assert "Trader" in node_names
        assert "Research Manager" in node_names
        assert "Portfolio Manager" not in node_names
        assert "Compliance Officer" not in node_names
        assert "Bull Researcher" not in node_names
        assert "Bear Researcher" not in node_names

    @patch("tradingagents.graph.setup.create_market_analyst", return_value=MagicMock())
    @patch("tradingagents.graph.setup.create_bull_researcher", return_value=MagicMock())
    @patch("tradingagents.graph.setup.create_bear_researcher", return_value=MagicMock())
    @patch("tradingagents.graph.setup.create_research_manager", return_value=MagicMock())
    @patch("tradingagents.graph.setup.create_trader", return_value=MagicMock())
    @patch("tradingagents.graph.setup.create_msg_delete", return_value=MagicMock())
    def test_stock_quick_trade_with_risk_manager(self, *mocks):
        gs = _make_setup()
        rm_node = MagicMock()
        workflow = gs.setup_graph(
            ["market"],
            risk_manager_node=rm_node,
            workflow_mode="quick_trade",
        )
        graph = workflow.compile()
        node_names = set(graph.get_graph().nodes.keys())
        assert "Risk Manager" in node_names
        assert "Portfolio Manager" not in node_names

    @patch("tradingagents.graph.setup.create_msg_delete", return_value=MagicMock())
    def test_crypto_quick_trade_compiles(self, mock_delete):
        gs = _make_setup()
        rm_node = MagicMock()
        workflow = gs.setup_crypto_graph(
            selected_analysts=["crypto_technical"],
            crypto_analyst_nodes={"crypto_technical": MagicMock()},
            crypto_tool_nodes={"crypto_technical": MagicMock()},
            crypto_trader_node=MagicMock(),
            crypto_bull_debater=None,
            crypto_bear_debater=None,
            crypto_portfolio_manager=None,
            confluence_checker_node=MagicMock(),
            crypto_bull_researcher=MagicMock(),
            crypto_bear_researcher=MagicMock(),
            crypto_research_manager=MagicMock(),
            risk_manager_node=rm_node,
            workflow_mode="quick_trade",
        )
        graph = workflow.compile()
        node_names = set(graph.get_graph().nodes.keys())
        assert "Trader" in node_names
        assert "Risk Manager" in node_names
        assert "Confluence Checker" in node_names
        assert "Research Manager" in node_names
        assert "Portfolio Manager" not in node_names
        assert "Compliance Officer" not in node_names
        assert "Bull Researcher" not in node_names
        assert "Bear Researcher" not in node_names
        assert "Bull Analyst" not in node_names
        assert "Bear Analyst" not in node_names
