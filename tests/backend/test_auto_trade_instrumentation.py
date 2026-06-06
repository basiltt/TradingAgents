"""Verify recorder failures never break trading (fail-open contract)."""

from unittest.mock import AsyncMock, MagicMock
import pytest

from backend.services.auto_trade_service import AutoTradeExecutor, _AccountState


def _exploding_recorder():
    rec = MagicMock()
    rec.emit_symbol_decision.side_effect = RuntimeError("boom")
    rec.emit_lifecycle.side_effect = RuntimeError("boom")
    rec.emit_exchange_snapshot.side_effect = RuntimeError("boom")
    rec.emit_account_trace.side_effect = RuntimeError("boom")
    return rec


@pytest.mark.asyncio
async def test_trade_succeeds_even_if_recorder_raises():
    """A successful trade must complete even when every emit raises."""
    accounts = AsyncMock()
    accounts.place_trade.return_value = {"trade_id": "t1", "side": "Sell"}
    accounts.get_mark_price.return_value = 100.0
    rec = _exploding_recorder()
    ctx = MagicMock()
    ex = AutoTradeExecutor(accounts, None, recorder=rec, debug_ctx=ctx)
    state = _AccountState(config={
        "account_id": "a1", "min_score": 0, "confidence_filter": "any",
        "execution_mode": "batch", "leverage": 5, "capital_pct": 10,
        "take_profit_pct": 150, "stop_loss_pct": 100, "direction": "straight",
    })
    state.base_capital = 1000.0
    result = {"status": "completed", "ticker": "FOO", "direction": "sell",
              "confidence": "high", "score": -7, "id": 1}
    out = await ex._try_trade(state, result, phase="batch")
    assert out is not None
    assert out.status == "success"
    assert state.trades_executed == 1
