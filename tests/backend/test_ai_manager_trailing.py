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
