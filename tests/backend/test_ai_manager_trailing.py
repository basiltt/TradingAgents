"""Unit tests for TrailingState."""
import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services.ai_manager_trailing import TrailingState, TrailingParams


class TestSLComputation:
    def test_long_sl_never_moves_backwards(self):
        result = TrailingState._compute_new_sl(
            side="Buy", current_sl=105.0, price=110.0, atr=2.0, atr_multiplier=2.0
        )
        assert result == 106.0

    def test_long_sl_stays_when_price_drops(self):
        result = TrailingState._compute_new_sl(
            side="Buy", current_sl=106.0, price=107.0, atr=2.0, atr_multiplier=2.0
        )
        assert result == 106.0

    def test_short_sl_never_moves_backwards(self):
        result = TrailingState._compute_new_sl(
            side="Sell", current_sl=95.0, price=90.0, atr=2.0, atr_multiplier=2.0
        )
        assert result == 94.0

    def test_short_sl_stays_when_price_rises(self):
        result = TrailingState._compute_new_sl(
            side="Sell", current_sl=94.0, price=93.0, atr=2.0, atr_multiplier=2.0
        )
        assert result == 94.0


class TestTPComputation:
    def test_long_tp_extends(self):
        tp = TrailingState._compute_new_tp(side="Buy", price=110.0, sl=106.0, tp_extension_factor=1.5)
        assert tp == 116.0

    def test_short_tp_extends(self):
        tp = TrailingState._compute_new_tp(side="Sell", price=90.0, sl=94.0, tp_extension_factor=1.5)
        assert tp == 84.0


class TestBreakevenGuard:
    def test_long_sl_minimum_is_breakeven(self):
        sl = TrailingState._enforce_breakeven_minimum(side="Buy", entry_price=100.0, candidate_sl=99.0)
        assert sl == 100.1

    def test_short_sl_minimum_is_breakeven(self):
        sl = TrailingState._enforce_breakeven_minimum(side="Sell", entry_price=100.0, candidate_sl=101.0)
        assert sl == 99.9


class TestTrailingLifecycle:
    @pytest.mark.asyncio
    async def test_cancel_stops_loop(self):
        params = TrailingParams(symbol="BTCUSDT", side="Buy", entry_price=100.0, position_idx=0, tick_interval_s=0.1)
        done_called = []
        client = AsyncMock()
        ts = TrailingState(
            params=params, initial_sl=99.0, initial_tp=110.0, initial_atr=2.0,
            ws_buffer={"positions": [{"symbol": "BTCUSDT", "markPrice": "105"}]},
            get_indicators_fn=lambda s: {"atr_14": 2.0, "adx_14": 30.0},
            get_client_fn=AsyncMock(return_value=client),
            on_done=lambda s: done_called.append(s),
        )
        ts.start()
        await asyncio.sleep(0.05)
        ts.cancel()
        await asyncio.sleep(0.2)
        assert not ts.is_active
        assert done_called == ["BTCUSDT"]

    @pytest.mark.asyncio
    async def test_position_gone_terminates(self):
        params = TrailingParams(symbol="BTCUSDT", side="Buy", entry_price=100.0, position_idx=0, tick_interval_s=0.1)
        ts = TrailingState(
            params=params, initial_sl=99.0, initial_tp=110.0, initial_atr=2.0,
            ws_buffer={"positions": []},
            get_indicators_fn=lambda s: {"atr_14": 2.0, "adx_14": 30.0},
            get_client_fn=AsyncMock(return_value=AsyncMock()),
        )
        ts.start()
        await asyncio.sleep(0.25)
        assert not ts.is_active

    @pytest.mark.asyncio
    async def test_suspend_skips_ticks(self):
        params = TrailingParams(symbol="BTCUSDT", side="Buy", entry_price=100.0, position_idx=0, tick_interval_s=0.1)
        client = AsyncMock()
        ts = TrailingState(
            params=params, initial_sl=99.0, initial_tp=110.0, initial_atr=2.0,
            ws_buffer={"positions": [{"symbol": "BTCUSDT", "markPrice": "115"}]},
            get_indicators_fn=lambda s: {"atr_14": 2.0, "adx_14": 30.0},
            get_client_fn=AsyncMock(return_value=client),
        )
        ts.start()
        ts.suspend()
        await asyncio.sleep(0.25)
        client.set_trading_stop.assert_not_called()
        ts.cancel()

    @pytest.mark.asyncio
    async def test_adx_below_threshold_exits(self):
        params = TrailingParams(symbol="BTCUSDT", side="Buy", entry_price=100.0, position_idx=0,
                               tick_interval_s=0.1, adx_exit_threshold=20.0)
        ts = TrailingState(
            params=params, initial_sl=99.0, initial_tp=110.0, initial_atr=2.0,
            ws_buffer={"positions": [{"symbol": "BTCUSDT", "markPrice": "105"}]},
            get_indicators_fn=lambda s: {"atr_14": 2.0, "adx_14": 15.0},
            get_client_fn=AsyncMock(return_value=AsyncMock()),
        )
        ts.start()
        await asyncio.sleep(0.25)
        assert not ts.is_active

    @pytest.mark.asyncio
    async def test_max_duration_exits(self):
        params = TrailingParams(symbol="BTCUSDT", side="Buy", entry_price=100.0, position_idx=0,
                               tick_interval_s=0.1, max_duration_s=0.2)
        ts = TrailingState(
            params=params, initial_sl=99.0, initial_tp=110.0, initial_atr=2.0,
            ws_buffer={"positions": [{"symbol": "BTCUSDT", "markPrice": "105"}]},
            get_indicators_fn=lambda s: {"atr_14": 2.0, "adx_14": 30.0},
            get_client_fn=AsyncMock(return_value=AsyncMock()),
        )
        ts.start()
        await asyncio.sleep(0.5)
        assert not ts.is_active

    @pytest.mark.asyncio
    async def test_max_api_failures_exits(self):
        params = TrailingParams(symbol="BTCUSDT", side="Buy", entry_price=100.0, position_idx=0,
                               tick_interval_s=0.1, max_api_failures=2)
        client = AsyncMock()
        client.set_trading_stop = AsyncMock(side_effect=Exception("network error"))
        ts = TrailingState(
            params=params, initial_sl=99.0, initial_tp=110.0, initial_atr=2.0,
            ws_buffer={"positions": [{"symbol": "BTCUSDT", "markPrice": "115"}]},
            get_indicators_fn=lambda s: {"atr_14": 2.0, "adx_14": 30.0},
            get_client_fn=AsyncMock(return_value=client),
        )
        ts.start()
        await asyncio.sleep(0.5)
        assert not ts.is_active


class TestTPNeverBackwards:
    @pytest.mark.asyncio
    async def test_long_tp_does_not_decrease_on_pullback(self):
        """TP must never decrease even when price pulls back."""
        prices = ["115", "112", "110"]  # price pulling back
        tick_idx = [0]
        client = AsyncMock()
        client.set_trading_stop = AsyncMock(return_value={})

        def fake_indicators(s):
            return {"atr_14": 2.0, "adx_14": 30.0}

        ws = {"positions": [{"symbol": "BTCUSDT", "markPrice": "115", "_ws_updated_at": time.time()}]}
        params = TrailingParams(symbol="BTCUSDT", side="Buy", entry_price=100.0,
                               position_idx=0, tick_interval_s=0.1, adx_exit_threshold=10.0)

        ts = TrailingState(
            params=params, initial_sl=110.0, initial_tp=120.0, initial_atr=2.0,
            ws_buffer=ws, get_indicators_fn=fake_indicators,
            get_client_fn=AsyncMock(return_value=client),
        )

        original_tick = TrailingState._tick
        async def update_tick(self_ts):
            tick_idx[0] = min(tick_idx[0] + 1, len(prices) - 1)
            ws["positions"][0]["markPrice"] = prices[tick_idx[0]]
            ws["positions"][0]["_ws_updated_at"] = time.time()
            await original_tick(self_ts)

        with patch.object(TrailingState, '_tick', update_tick):
            ts.start()
            await asyncio.sleep(0.5)
            ts.cancel()

        # TP should stay at initial 120 or higher, never decrease
        for call in client.set_trading_stop.call_args_list:
            tp_arg = call.kwargs.get("take_profit")
            if tp_arg is not None:
                assert float(tp_arg) >= 120.0, f"TP moved backwards to {tp_arg}"


class TestResumeFromSweep:
    @pytest.mark.asyncio
    async def test_resume_resets_sl_and_continues(self):
        params = TrailingParams(symbol="BTCUSDT", side="Buy", entry_price=100.0,
                               position_idx=0, tick_interval_s=0.1, adx_exit_threshold=10.0)
        client = AsyncMock()
        client.set_trading_stop = AsyncMock(return_value={})
        ws = {"positions": [{"symbol": "BTCUSDT", "markPrice": "115", "_ws_updated_at": time.time()}]}

        ts = TrailingState(
            params=params, initial_sl=110.0, initial_tp=120.0, initial_atr=2.0,
            ws_buffer=ws, get_indicators_fn=lambda s: {"atr_14": 2.0, "adx_14": 30.0},
            get_client_fn=AsyncMock(return_value=client),
        )
        ts.start()
        # Suspend (sweep defense)
        ts.suspend()
        await asyncio.sleep(0.15)
        assert client.set_trading_stop.call_count == 0  # no calls while suspended

        # Resume with a lower SL (sweep widened it)
        ts.resume_from_sweep(105.0)
        assert ts._current_sl == 105.0
        assert not ts._suspended
        await asyncio.sleep(0.15)
        # After resume, should have made at least one call
        assert client.set_trading_stop.call_count >= 1
        ts.cancel()


class TestMiniLLMTighten:
    @pytest.mark.asyncio
    async def test_tighten_reduces_atr_multiplier(self):
        params = TrailingParams(symbol="BTCUSDT", side="Buy", entry_price=100.0,
                               position_idx=0, tick_interval_s=0.1,
                               mini_llm_every_n_ticks=1, adx_exit_threshold=10.0)
        client = AsyncMock()
        client.set_trading_stop = AsyncMock(return_value={})

        async def fake_mini_llm(**kwargs):
            return "TIGHTEN momentum weakening"

        ws = {"positions": [{"symbol": "BTCUSDT", "markPrice": "115", "_ws_updated_at": time.time()}]}
        ts = TrailingState(
            params=params, initial_sl=110.0, initial_tp=120.0, initial_atr=2.0,
            ws_buffer=ws, get_indicators_fn=lambda s: {"atr_14": 2.0, "adx_14": 30.0},
            get_client_fn=AsyncMock(return_value=client),
            mini_llm_fn=fake_mini_llm,
        )
        original_mult = ts._params.atr_multiplier
        ts.start()
        await asyncio.sleep(0.25)
        ts.cancel()
        # ATR multiplier should have been reduced (0.75x per TIGHTEN)
        assert ts._params.atr_multiplier < original_mult
    @pytest.mark.asyncio
    async def test_trailing_full_cycle(self):
        """End-to-end: start trailing → SL moves up → ADX fades → exits."""
        tick_count = [0]
        adx_values = [30, 30, 30, 15]  # fades on 4th tick

        def fake_indicators(symbol):
            idx = min(tick_count[0], len(adx_values) - 1)
            return {"atr_14": 2.0, "adx_14": adx_values[idx]}

        client = AsyncMock()
        client.set_trading_stop = AsyncMock(return_value={})

        prices = ["105", "108", "112", "112"]
        ws = {"positions": [{"symbol": "BTCUSDT", "markPrice": "105", "side": "Buy", "_ws_updated_at": time.time()}]}

        params = TrailingParams(
            symbol="BTCUSDT", side="Buy", entry_price=100.0,
            position_idx=0, tick_interval_s=0.1, adx_exit_threshold=20.0,
        )

        done_events = []

        # Patch _tick to increment counter and update price before real logic
        original_tick = TrailingState._tick

        async def counting_tick(self_ts):
            tick_count[0] += 1
            idx = min(tick_count[0], len(prices) - 1)
            ws["positions"][0]["markPrice"] = prices[idx]
            ws["positions"][0]["_ws_updated_at"] = time.time()
            await original_tick(self_ts)

        ts = TrailingState(
            params=params, initial_sl=96.0, initial_tp=114.0, initial_atr=2.0,
            ws_buffer=ws,
            get_indicators_fn=fake_indicators,
            get_client_fn=AsyncMock(return_value=client),
            on_done=lambda s: done_events.append(s),
        )

        with patch.object(TrailingState, '_tick', counting_tick):
            ts.start()
            await asyncio.sleep(0.8)

        assert not ts.is_active
        assert done_events == ["BTCUSDT"]
        # SL should have moved up — at least one set_trading_stop call made
        assert client.set_trading_stop.call_count >= 1
