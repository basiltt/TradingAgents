"""Tests for performance optimizations — parallel pre-fetch, TTL cache, timestamp pinning."""

import threading
import time
from unittest.mock import MagicMock, patch


class TestTTLCache:
    """TTLCache uses composition (not dict inheritance) with periodic sweep."""

    def test_basic_set_and_get(self):
        from tradingagents.dataflows.bybit_data import TTLCache

        c = TTLCache(ttl_seconds=10.0)
        c["key"] = "value"
        assert c["key"] == "value"
        assert "key" in c

    def test_expired_entry_not_found(self):
        from tradingagents.dataflows.bybit_data import TTLCache

        c = TTLCache(ttl_seconds=0.05)
        c["key"] = "value"
        time.sleep(0.1)
        assert "key" not in c

    def test_get_with_default(self):
        from tradingagents.dataflows.bybit_data import TTLCache

        c = TTLCache(ttl_seconds=10.0)
        assert c.get("missing", "default") == "default"
        c["present"] = 42
        assert c.get("present", "default") == 42

    def test_expired_get_returns_default(self):
        from tradingagents.dataflows.bybit_data import TTLCache

        c = TTLCache(ttl_seconds=0.05)
        c["key"] = "value"
        time.sleep(0.1)
        assert c.get("key", "gone") == "gone"

    def test_overwrite_resets_ttl(self):
        from tradingagents.dataflows.bybit_data import TTLCache

        c = TTLCache(ttl_seconds=0.2)
        c["key"] = "v1"
        time.sleep(0.1)
        c["key"] = "v2"
        time.sleep(0.15)
        assert c["key"] == "v2"

    def test_not_a_dict_subclass(self):
        from tradingagents.dataflows.bybit_data import TTLCache

        c = TTLCache(ttl_seconds=10.0)
        assert not isinstance(c, dict)
        assert not hasattr(c, "keys")
        assert not hasattr(c, "values")
        assert not hasattr(c, "items")

    def test_sweep_purges_expired_entries(self):
        from tradingagents.dataflows.bybit_data import TTLCache

        c = TTLCache(ttl_seconds=0.01)
        for i in range(100):
            c[f"key_{i}"] = i
        time.sleep(0.05)
        # Force sweep by writing enough entries
        for i in range(c._SWEEP_INTERVAL):
            c[f"new_{i}"] = i
        # Expired entries should have been swept — none of the originals remain
        for i in range(100):
            assert f"key_{i}" not in c

    def test_get_is_atomic_no_toctou(self):
        """get() should be a single locked operation — no race between check and read."""
        from tradingagents.dataflows.bybit_data import TTLCache

        c = TTLCache(ttl_seconds=0.05)
        c["key"] = "value"
        time.sleep(0.04)
        # Near expiry — .get() should either return the value or the default, never raise
        result = c.get("key", "expired")
        assert result in ("value", "expired")

    def test_thread_safety(self):
        from tradingagents.dataflows.bybit_data import TTLCache

        c = TTLCache(ttl_seconds=5.0)

        def writer(start):
            for i in range(100):
                c[f"key_{start + i}"] = start + i

        def reader(start):
            for i in range(100):
                c.get(f"key_{start + i}")

        threads = [
            threading.Thread(target=writer, args=(0,)),
            threading.Thread(target=writer, args=(100,)),
            threading.Thread(target=reader, args=(0,)),
            threading.Thread(target=reader, args=(100,)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        # Verify data integrity — all 200 keys written with correct values
        for i in range(200):
            assert c.get(f"key_{i}") == i


class TestParallelPriceFetch:
    """build_current_price_context should fetch all 6 endpoints concurrently."""

    @patch("tradingagents.dataflows.bybit_data.get_bybit_klines", return_value="kline_data")
    @patch("tradingagents.dataflows.bybit_data.get_bybit_ticker", return_value="ticker_data")
    def test_returns_all_sections(self, mock_ticker, mock_klines):
        from tradingagents.dataflows.bybit_data import build_current_price_context

        result = build_current_price_context("BTCUSDT", as_of_ms=1000000000000)
        assert "LIVE PRICE SNAPSHOT" in result
        assert "5-MIN CANDLES" in result
        assert "15-MIN CANDLES" in result
        assert "1-HOUR CANDLES" in result
        assert "4-HOUR CANDLES" in result
        assert "DAILY CANDLES" in result

    @patch("tradingagents.dataflows.bybit_data.get_bybit_klines", return_value="kline_data")
    @patch("tradingagents.dataflows.bybit_data.get_bybit_ticker", return_value="ticker_data")
    def test_primary_interval_tagged(self, mock_ticker, mock_klines):
        from tradingagents.dataflows.bybit_data import build_current_price_context

        result = build_current_price_context("BTCUSDT", as_of_ms=1000000000000, primary_interval="60")
        assert "(PRIMARY TIMEFRAME)" in result

    @patch("tradingagents.dataflows.bybit_data.get_bybit_klines", side_effect=Exception("API down"))
    @patch("tradingagents.dataflows.bybit_data.get_bybit_ticker", side_effect=Exception("API down"))
    def test_handles_all_failures_gracefully(self, mock_ticker, mock_klines):
        from tradingagents.dataflows.bybit_data import build_current_price_context

        result = build_current_price_context("BTCUSDT", as_of_ms=1000000000000)
        assert "Unavailable" in result
        assert "LIVE PRICE SNAPSHOT" in result

    @patch("tradingagents.dataflows.bybit_data.get_bybit_klines", return_value="kline_data")
    @patch("tradingagents.dataflows.bybit_data.get_bybit_ticker", return_value="ticker_data")
    def test_sections_in_correct_order(self, mock_ticker, mock_klines):
        from tradingagents.dataflows.bybit_data import build_current_price_context

        result = build_current_price_context("BTCUSDT", as_of_ms=1000000000000)
        live_pos = result.index("LIVE PRICE")
        five_pos = result.index("5-MIN")
        fifteen_pos = result.index("15-MIN")
        one_h_pos = result.index("1-HOUR")
        four_h_pos = result.index("4-HOUR")
        daily_pos = result.index("DAILY")
        assert live_pos < five_pos < fifteen_pos < one_h_pos < four_h_pos < daily_pos


class TestBackgroundPrefetch:
    """_run_graph should start pre-fetch in a background thread."""

    @patch("tradingagents.dataflows.bybit_data.build_current_price_context", return_value="price data")
    def test_prefetch_result_injected_into_state(self, mock_build):
        """Verify the pre-fetch result ends up in init_agent_state."""
        graph = self._make_graph_stub()

        graph._run_graph("BTCUSDT", "2026-01-01")

        mock_build.assert_called_once()
        # Verify pinned timestamp was passed
        _, kwargs = mock_build.call_args
        assert kwargs.get("as_of_ms") is not None
        # Verify price context reached the graph
        state_passed = graph.graph.invoke.call_args[0][0]
        assert state_passed["current_price_context"] == "price data"

    @staticmethod
    def _make_graph_stub():
        """Build a minimal TradingAgentsGraph stub for pre-fetch tests."""
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
        graph.config = {
            "asset_type": "crypto", "crypto_interval": "60",
            "checkpoint_enabled": False,
        }
        graph._crypto_shared = {
            "cache": {}, "limiter": MagicMock(), "circuit_breaker": MagicMock(),
            "api_key": None, "api_secret": None,
        }
        graph.memory_log = MagicMock()
        graph.memory_log.get_past_context.return_value = ""
        graph.propagator = MagicMock()
        graph.propagator.create_initial_state.return_value = {"messages": []}
        graph.propagator.get_graph_args.return_value = {}
        graph.debug = False
        graph.graph = MagicMock()
        graph.graph.invoke.return_value = {
            "final_trade_decision": "hold",
            "investment_debate_state": {},
            "risk_debate_state": {},
            "company_of_interest": "BTC",
            "trade_date": "2026-01-01",
        }
        graph.log_states_dict = {}
        graph.reflector = MagicMock()
        graph.ticker = "BTCUSDT"
        graph._log_state = MagicMock()
        graph._checkpointer_ctx = None
        graph.process_signal = MagicMock(return_value=(0, "hold"))
        return graph

    @patch("tradingagents.dataflows.bybit_data.build_current_price_context",
           side_effect=Exception("API exploded"))
    def test_prefetch_error_produces_degraded_message(self, mock_build):
        graph = self._make_graph_stub()
        graph._run_graph("BTCUSDT", "2026-01-01")

        state_passed = graph.graph.invoke.call_args[0][0]
        assert "unavailable" in state_passed["current_price_context"].lower()
        assert "API exploded" in state_passed["current_price_context"]

    @patch("tradingagents.dataflows.bybit_data.build_current_price_context")
    def test_prefetch_timeout_produces_degraded_message(self, mock_build):
        mock_build.side_effect = lambda *a, **kw: time.sleep(60)

        graph = self._make_graph_stub()
        # Monkey-patch join timeout to 0.1s so test is fast
        original_run_graph = graph._run_graph.__func__

        import types

        def fast_timeout_run(self_inner, company, date):
            import threading as _threading
            orig_thread_init = _threading.Thread.__init__

            def patched_init(t_self, *a, **kw):
                orig_thread_init(t_self, *a, **kw)
                t_self._original_join = t_self.join
                t_self.join = lambda timeout=None: t_self._original_join(timeout=0.1)

            with patch.object(_threading.Thread, '__init__', patched_init):
                return original_run_graph(self_inner, company, date)

        graph._run_graph = types.MethodType(fast_timeout_run, graph)
        graph._run_graph("BTCUSDT", "2026-01-01")

        state_passed = graph.graph.invoke.call_args[0][0]
        assert "timeout" in state_passed["current_price_context"].lower()

    def test_partial_kline_failure(self):
        """Partial failures produce mix of data and Unavailable."""
        with patch("tradingagents.dataflows.bybit_data.get_bybit_ticker",
                    return_value="BTC @ 100000"), \
             patch("tradingagents.dataflows.bybit_data.get_bybit_klines") as mock_klines:
            from tradingagents.dataflows.bybit_data import build_current_price_context

            def selective_fail(symbol, interval, *args, **kwargs):
                if interval == "5":
                    raise Exception("5m endpoint down")
                return "candle data"

            mock_klines.side_effect = selective_fail
            result = build_current_price_context("BTCUSDT", as_of_ms=1000000000000)
            assert "LIVE PRICE" in result
            assert "Unavailable" in result


class TestSharedSingletons:
    """get_shared_limiter / get_shared_circuit_breaker return stable singletons."""

    def test_limiter_returns_same_instance(self):
        from tradingagents.dataflows.bybit_data import get_shared_limiter
        a = get_shared_limiter()
        b = get_shared_limiter()
        assert a is b

    def test_circuit_breaker_returns_same_instance(self):
        from tradingagents.dataflows.bybit_data import get_shared_circuit_breaker
        a = get_shared_circuit_breaker()
        b = get_shared_circuit_breaker()
        assert a is b

    def test_limiter_concurrent_first_access(self):
        from tradingagents.dataflows import bybit_data
        from tradingagents.dataflows.bybit_data import get_shared_limiter

        old = bybit_data._shared_limiter
        bybit_data._shared_limiter = None
        try:
            results = []

            def grab():
                results.append(get_shared_limiter())

            threads = [threading.Thread(target=grab) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)
            assert all(r is results[0] for r in results)
        finally:
            bybit_data._shared_limiter = old
