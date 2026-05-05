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
