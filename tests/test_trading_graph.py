"""Tests for tradingagents.graph.trading_graph._get_provider_kwargs — Phase 1 unit tests."""

from unittest.mock import patch, MagicMock
import pytest


class TestConstructor:
    @patch("tradingagents.graph.trading_graph.set_config")
    @patch("tradingagents.graph.trading_graph.os.makedirs")
    @patch("tradingagents.graph.trading_graph.create_llm_client")
    @patch("tradingagents.graph.trading_graph.TradingMemoryLog")
    @patch("tradingagents.graph.trading_graph.ConditionalLogic")
    @patch("tradingagents.graph.trading_graph.GraphSetup")
    @patch("tradingagents.graph.trading_graph.Propagator")
    @patch("tradingagents.graph.trading_graph.Reflector")
    @patch("tradingagents.graph.trading_graph.SignalProcessor")
    def test_stock_init(self, mock_sp, mock_ref, mock_prop, mock_gs, mock_cl,
                        mock_ml, mock_llm, mock_mkdirs, mock_set_cfg):
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        mock_client = MagicMock()
        mock_client.get_llm.return_value = MagicMock()
        mock_llm.return_value = mock_client
        mock_gs_inst = MagicMock()
        mock_gs_inst.setup_graph.return_value = MagicMock()
        mock_gs_inst.setup_graph.return_value.compile.return_value = MagicMock()
        mock_gs.return_value = mock_gs_inst

        config = {
            "llm_provider": "openai",
            "deep_think_llm": "gpt-4o",
            "quick_think_llm": "gpt-4o-mini",
            "data_cache_dir": "/tmp/cache",
            "results_dir": "/tmp/results",
            "max_debate_rounds": 3,
            "max_risk_discuss_rounds": 3,
            "asset_type": "stock",
        }
        obj = TradingAgentsGraph(selected_analysts=["market"], config=config)
        assert obj.debug is False
        assert mock_llm.call_count == 2
        mock_mkdirs.assert_called()
        mock_gs_inst.setup_graph.assert_called_once()
        call_args = mock_gs_inst.setup_graph.call_args
        assert call_args[0][0] == ["market"]

    @patch("tradingagents.graph.trading_graph.set_config")
    @patch("tradingagents.graph.trading_graph.os.makedirs")
    @patch("tradingagents.graph.trading_graph.create_llm_client")
    @patch("tradingagents.graph.trading_graph.TradingMemoryLog")
    @patch("tradingagents.graph.trading_graph.ConditionalLogic")
    @patch("tradingagents.graph.trading_graph.GraphSetup")
    @patch("tradingagents.graph.trading_graph.Propagator")
    @patch("tradingagents.graph.trading_graph.Reflector")
    @patch("tradingagents.graph.trading_graph.SignalProcessor")
    def test_crypto_init(self, mock_sp, mock_ref, mock_prop, mock_gs, mock_cl,
                         mock_ml, mock_llm, mock_mkdirs, mock_set_cfg):
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        mock_client = MagicMock()
        mock_client.get_llm.return_value = MagicMock()
        mock_llm.return_value = mock_client
        mock_gs_inst = MagicMock()
        mock_gs_inst.setup_crypto_graph.return_value = MagicMock()
        mock_gs_inst.setup_crypto_graph.return_value.compile.return_value = MagicMock()
        mock_gs.return_value = mock_gs_inst

        config = {
            "llm_provider": "openai",
            "deep_think_llm": "gpt-4o",
            "quick_think_llm": "gpt-4o-mini",
            "data_cache_dir": "/tmp/cache",
            "results_dir": "/tmp/results",
            "max_debate_rounds": 3,
            "max_risk_discuss_rounds": 3,
            "asset_type": "crypto",
        }

        with patch("tradingagents.agents.utils.crypto_agent_utils.make_crypto_tools", return_value=[]), \
             patch("tradingagents.agents.utils.coingecko_tools.make_coingecko_tools", return_value=[]), \
             patch("tradingagents.dataflows.bybit_data.BybitRateLimiter"), \
             patch("tradingagents.dataflows.bybit_data.BybitCircuitBreaker"), \
             patch("tradingagents.agents.crypto_analysts.create_crypto_trader", return_value=MagicMock()), \
             patch("tradingagents.agents.crypto_analysts.create_crypto_risk_bull_debater", return_value=MagicMock()), \
             patch("tradingagents.agents.crypto_analysts.create_crypto_risk_bear_debater", return_value=MagicMock()), \
             patch("tradingagents.agents.crypto_analysts.create_crypto_portfolio_manager", return_value=MagicMock()):
            obj = TradingAgentsGraph(
                selected_analysts=["crypto_technical", "crypto_news"],
                config=config,
            )
            mock_gs_inst.setup_crypto_graph.assert_called_once()

    @patch("tradingagents.graph.trading_graph.set_config")
    @patch("tradingagents.graph.trading_graph.os.makedirs")
    @patch("tradingagents.graph.trading_graph.create_llm_client")
    @patch("tradingagents.graph.trading_graph.TradingMemoryLog")
    @patch("tradingagents.graph.trading_graph.ConditionalLogic")
    @patch("tradingagents.graph.trading_graph.GraphSetup")
    @patch("tradingagents.graph.trading_graph.Propagator")
    @patch("tradingagents.graph.trading_graph.Reflector")
    @patch("tradingagents.graph.trading_graph.SignalProcessor")
    def test_with_callbacks(self, mock_sp, mock_ref, mock_prop, mock_gs, mock_cl,
                            mock_ml, mock_llm, mock_mkdirs, mock_set_cfg):
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        mock_client = MagicMock()
        mock_client.get_llm.return_value = MagicMock()
        mock_llm.return_value = mock_client
        mock_gs_inst = MagicMock()
        mock_gs_inst.setup_graph.return_value.compile.return_value = MagicMock()
        mock_gs.return_value = mock_gs_inst

        cb = MagicMock()
        config = {
            "llm_provider": "openai",
            "deep_think_llm": "gpt-4o",
            "quick_think_llm": "gpt-4o-mini",
            "data_cache_dir": "/tmp/cache",
            "results_dir": "/tmp/results",
            "max_debate_rounds": 3,
            "max_risk_discuss_rounds": 3,
        }
        obj = TradingAgentsGraph(config=config, callbacks=[cb])
        call_kwargs = mock_llm.call_args_list[0][1]
        assert "callbacks" in call_kwargs


class TestCreateToolNodes:
    def test_returns_four_nodes(self):
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        obj = object.__new__(TradingAgentsGraph)
        nodes = obj._create_tool_nodes()
        assert set(nodes.keys()) == {"market", "social", "news", "fundamentals"}


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

    @patch.object(
        __import__("tradingagents.graph.trading_graph", fromlist=["TradingAgentsGraph"]).TradingAgentsGraph,
        "_fetch_returns",
    )
    def test_updates_with_outcomes(self, mock_fetch):
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        obj = object.__new__(TradingAgentsGraph)
        obj.memory_log = MagicMock()
        obj.memory_log.get_pending_entries.return_value = [
            {"ticker": "AAPL", "date": "2025-01-10", "decision": "buy"},
        ]
        obj.reflector = MagicMock()
        obj.reflector.reflect_on_final_decision.return_value = "good call"
        mock_fetch.return_value = (0.05, 0.02, 5)
        obj._resolve_pending_entries("AAPL")
        obj.memory_log.batch_update_with_outcomes.assert_called_once()
        updates = obj.memory_log.batch_update_with_outcomes.call_args[0][0]
        assert len(updates) == 1
        assert updates[0]["raw_return"] == 0.05
        assert updates[0]["alpha_return"] == 0.02
        assert updates[0]["reflection"] == "good call"


class TestRunGraph:
    def test_invoke_mode(self, tmp_path):
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        obj = object.__new__(TradingAgentsGraph)
        obj.debug = False
        obj.config = {"results_dir": str(tmp_path), "asset_type": "stock"}
        obj.ticker = "AAPL"
        obj.log_states_dict = {}
        obj.memory_log = MagicMock()
        obj.propagator = MagicMock()
        obj.propagator.create_initial_state.return_value = {"company_of_interest": "AAPL", "trade_date": "2025-01-10"}
        obj.propagator.get_graph_args.return_value = {}
        obj.signal_processor = MagicMock()
        obj.signal_processor.process_signal.return_value = "BUY"
        final = {
            "company_of_interest": "AAPL",
            "trade_date": "2025-01-10",
            "final_trade_decision": "Buy AAPL",
            "investment_debate_state": None,
            "risk_debate_state": None,
        }
        obj.graph = MagicMock()
        obj.graph.invoke.return_value = final
        result_state, signal = obj._run_graph("AAPL", "2025-01-10")
        assert result_state["final_trade_decision"] == "Buy AAPL"
        assert signal == "BUY"
        obj.memory_log.store_decision.assert_called_once()

    def test_debug_mode(self, tmp_path):
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        obj = object.__new__(TradingAgentsGraph)
        obj.debug = True
        obj.config = {"results_dir": str(tmp_path), "asset_type": "stock"}
        obj.ticker = "AAPL"
        obj.log_states_dict = {}
        obj.memory_log = MagicMock()
        obj.propagator = MagicMock()
        obj.propagator.create_initial_state.return_value = {}
        obj.propagator.get_graph_args.return_value = {}
        obj.signal_processor = MagicMock()
        obj.signal_processor.process_signal.return_value = "HOLD"

        msg = MagicMock()
        chunk = {
            "messages": [msg],
            "company_of_interest": "AAPL",
            "trade_date": "2025-01-10",
            "final_trade_decision": "Hold",
            "investment_debate_state": None,
            "risk_debate_state": None,
        }
        obj.graph = MagicMock()
        obj.graph.stream.return_value = [chunk]
        result_state, signal = obj._run_graph("AAPL", "2025-01-10")
        assert result_state["final_trade_decision"] == "Hold"
        msg.pretty_print.assert_called_once()

    def test_checkpoint_thread_id(self, tmp_path):
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        obj = object.__new__(TradingAgentsGraph)
        obj.debug = False
        obj.config = {
            "results_dir": str(tmp_path),
            "asset_type": "stock",
            "checkpoint_enabled": True,
            "data_cache_dir": str(tmp_path),
        }
        obj.ticker = "AAPL"
        obj.log_states_dict = {}
        obj.memory_log = MagicMock()
        obj.propagator = MagicMock()
        obj.propagator.create_initial_state.return_value = {}
        obj.propagator.get_graph_args.return_value = {}
        obj.signal_processor = MagicMock()
        obj.signal_processor.process_signal.return_value = "BUY"
        final = {
            "company_of_interest": "AAPL",
            "trade_date": "2025-01-10",
            "final_trade_decision": "Buy",
            "investment_debate_state": None,
            "risk_debate_state": None,
        }
        obj.graph = MagicMock()
        obj.graph.invoke.return_value = final
        with patch("tradingagents.graph.trading_graph.clear_checkpoint") as mock_clear:
            result_state, _ = obj._run_graph("AAPL", "2025-01-10")
            mock_clear.assert_called_once()


class TestPropagate:
    def test_basic_propagate(self, tmp_path):
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        obj = object.__new__(TradingAgentsGraph)
        obj.config = {"results_dir": str(tmp_path), "asset_type": "stock"}
        obj.memory_log = MagicMock()
        obj.memory_log.get_pending_entries.return_value = []
        obj._checkpointer_ctx = None

        final = {
            "company_of_interest": "AAPL",
            "trade_date": "2025-01-10",
            "final_trade_decision": "Buy",
            "investment_debate_state": None,
            "risk_debate_state": None,
        }
        with patch.object(TradingAgentsGraph, "_run_graph", return_value=(final, "BUY")):
            result = obj.propagate("AAPL", "2025-01-10")
            assert result == (final, "BUY")
            assert obj.ticker == "AAPL"

    @patch("tradingagents.graph.trading_graph.get_checkpointer")
    @patch("tradingagents.graph.trading_graph.checkpoint_step")
    def test_checkpoint_propagate(self, mock_step, mock_get_cp, tmp_path):
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        obj = object.__new__(TradingAgentsGraph)
        obj.config = {
            "results_dir": str(tmp_path),
            "asset_type": "stock",
            "checkpoint_enabled": True,
            "data_cache_dir": str(tmp_path),
        }
        obj.memory_log = MagicMock()
        obj.memory_log.get_pending_entries.return_value = []
        obj._checkpointer_ctx = None
        obj.workflow = MagicMock()

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=MagicMock())
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_get_cp.return_value = mock_ctx
        mock_step.return_value = None

        final = {"final_trade_decision": "Buy", "company_of_interest": "AAPL", "trade_date": "2025-01-10", "investment_debate_state": None, "risk_debate_state": None}
        with patch.object(TradingAgentsGraph, "_run_graph", return_value=(final, "BUY")):
            result = obj.propagate("AAPL", "2025-01-10")
            mock_get_cp.assert_called_once()
            mock_ctx.__exit__.assert_called_once()
            obj.workflow.compile.assert_called()
            assert obj._checkpointer_ctx is None
