"""Tests for tradingagents.graph.trading_graph._get_provider_kwargs — Phase 1 unit tests."""

from unittest.mock import patch, MagicMock
import pytest


class TestGetProviderKwargs:
    def _make_graph_with_config(self, config):
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        obj = object.__new__(TradingAgentsGraph)
        obj.config = config
        return obj

    def test_google_thinking_level(self):
        obj = self._make_graph_with_config({
            "llm_provider": "google",
            "google_thinking_level": "medium",
        })
        result = obj._get_provider_kwargs()
        assert result == {"thinking_level": "medium"}

    def test_google_no_thinking_level(self):
        obj = self._make_graph_with_config({
            "llm_provider": "google",
        })
        result = obj._get_provider_kwargs()
        assert result == {}

    def test_openai_reasoning_effort(self):
        obj = self._make_graph_with_config({
            "llm_provider": "openai",
            "openai_reasoning_effort": "high",
        })
        result = obj._get_provider_kwargs()
        assert result == {"reasoning_effort": "high"}

    def test_anthropic_effort(self):
        obj = self._make_graph_with_config({
            "llm_provider": "anthropic",
            "anthropic_effort": "high",
        })
        result = obj._get_provider_kwargs()
        assert result == {"effort": "high"}

    def test_unknown_provider_empty(self):
        obj = self._make_graph_with_config({
            "llm_provider": "unknown",
        })
        result = obj._get_provider_kwargs()
        assert result == {}


class TestFetchReturns:
    def _make_graph(self):
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        obj = object.__new__(TradingAgentsGraph)
        return obj

    @patch("tradingagents.graph.trading_graph.yf")
    def test_normal_return(self, mock_yf):
        import pandas as pd
        obj = self._make_graph()

        stock_data = pd.DataFrame({"Close": [100.0, 105.0, 110.0]})
        spy_data = pd.DataFrame({"Close": [400.0, 404.0, 408.0]})
        mock_yf.Ticker.side_effect = lambda t: MagicMock(history=MagicMock(
            return_value=stock_data if t != "SPY" else spy_data
        ))

        raw, alpha, days = obj._fetch_returns("AAPL", "2025-01-10", holding_days=1)
        assert raw is not None
        assert days == 1
        assert abs(raw - 0.05) < 0.001  # (105-100)/100

    @patch("tradingagents.graph.trading_graph.yf")
    def test_insufficient_data(self, mock_yf):
        import pandas as pd
        obj = self._make_graph()
        mock_yf.Ticker.return_value.history.return_value = pd.DataFrame({"Close": [100.0]})
        raw, alpha, days = obj._fetch_returns("AAPL", "2025-01-10")
        assert raw is None

    @patch("tradingagents.graph.trading_graph.yf")
    def test_exception_returns_none(self, mock_yf):
        obj = self._make_graph()
        mock_yf.Ticker.side_effect = Exception("network error")
        raw, alpha, days = obj._fetch_returns("AAPL", "2025-01-10")
        assert raw is None


class TestLogState:
    def test_writes_json(self, tmp_path):
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        obj = object.__new__(TradingAgentsGraph)
        obj.config = {"results_dir": str(tmp_path)}
        obj.ticker = "AAPL"
        obj.log_states_dict = {}

        state = {
            "company_of_interest": "AAPL",
            "trade_date": "2025-01-10",
            "investment_debate_state": None,
            "risk_debate_state": None,
        }
        obj._log_state("2025-01-10", state)

        import json
        log_dir = tmp_path / "AAPL" / "TradingAgentsStrategy_logs"
        assert log_dir.exists()
        files = list(log_dir.glob("*.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text())
        assert data["company_of_interest"] == "AAPL"


class TestResolvePendingEntries:
    def test_no_pending_is_noop(self):
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        obj = object.__new__(TradingAgentsGraph)
        obj.memory_log = MagicMock()
        obj.memory_log.get_pending_entries.return_value = []
        obj._resolve_pending_entries("AAPL")
        obj.memory_log.batch_update_with_outcomes.assert_not_called()

    @patch.object(
        __import__("tradingagents.graph.trading_graph", fromlist=["TradingAgentsGraph"]).TradingAgentsGraph,
        "_fetch_returns",
    )
    def test_skips_unavailable_prices(self, mock_fetch):
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        obj = object.__new__(TradingAgentsGraph)
        obj.memory_log = MagicMock()
        obj.memory_log.get_pending_entries.return_value = [
            {"ticker": "AAPL", "date": "2025-01-10", "decision": "buy"},
        ]
        obj.reflector = MagicMock()
        mock_fetch.return_value = (None, None, None)
        obj._resolve_pending_entries("AAPL")
        obj.memory_log.batch_update_with_outcomes.assert_not_called()
