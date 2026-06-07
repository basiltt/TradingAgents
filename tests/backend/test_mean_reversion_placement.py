"""Integration tests for the F2 mean-reversion placement branch (Phase 4)."""

from datetime import datetime, timedelta, timezone

import pytest

from backend.services.auto_trade_service import AutoTradeExecutor
from backend.services.scan_context import ScanContext


class _StubAccounts:
    def __init__(self, db=None):
        self.calls = []
        self._db = db

    async def place_trade(self, **kwargs):
        self.calls.append(kwargs)
        return {"trade_id": f"t{len(self.calls)}", "side": kwargs.get("signal_direction")}


class _AckPool:
    def __init__(self, row=None):
        self._row = row

    async def fetchrow(self, *a):
        return self._row


class _AckDB:
    def __init__(self, row=None):
        self.pool = _AckPool(row)


def _mr_cfg(**kw):
    base = {"account_id": "a", "strategy_cohort": "mean_reversion", "mean_reversion_enabled": True,
            "mr_regime": "ranging", "min_score": 6, "mr_extreme_min_abs_score": 5.0,
            "mr_mean_period": 20, "mr_mean_interval": "1h", "mr_leverage": 10,
            "mr_capital_pct": 2.0, "mr_target_capture_pct": 60.0, "mr_min_edge_pct": 1.0,
            "mr_tight_stop_pct": 6.0,  # tighter than the ~11.76% MR TP (avoids inverted geometry)
            "mr_short_enabled": True, "mr_long_enabled": False, "regime_staleness_minutes": 30}
    base.update(kw)
    return base


def _ctx(regime="ranging", symbol="BTCUSDT", price=102.0, mean=100.0, fresh=True, db_now=None):
    now = datetime.now(timezone.utc)
    computed = now if fresh else now - timedelta(minutes=60)
    return ScanContext(
        btc={("1h", 14): {"regime": regime, "vol_value": 1.0, "unavailable": False}},
        means={(symbol, 20, "1h"): mean},
        prices={symbol: price},
        computed_at=computed,
    )


def _executor(cfg, ctx, db=None):
    ex = AutoTradeExecutor(_StubAccounts(db=db))
    ex.init_configs([cfg])
    for st in ex._state.values():
        st.base_capital = 1000.0
    ex.set_scan_context(ctx)
    return ex


def _spy(ex):
    seen = []
    orig = ex._emit_decision

    def s(account_id, phase, symbol, decision, reason_code, result, **detail):
        seen.append((decision, str(reason_code)))
        return orig(account_id, phase, symbol, decision, reason_code, result, **detail)

    ex._emit_decision = s
    return seen


def _overbought():  # high score sell-ish extreme; entry above mean => short fade
    return {"status": "completed", "ticker": "BTC", "direction": "sell", "score": 8, "id": "r1"}


@pytest.mark.asyncio
async def test_mr_short_fade_places_with_strategy_kind():
    ex = _executor(_mr_cfg(), _ctx(price=102.0, mean=100.0))
    await ex._try_trade(list(ex._state.values())[0], _overbought(), phase="batch")
    assert len(ex._accounts.calls) == 1
    call = ex._accounts.calls[0]
    assert call["strategy_kind"] == "mean_reversion"
    assert call["leverage"] == 10                    # mr_leverage, not trend 20
    assert call["capital_pct"] == 2.0                # mr_capital_pct
    # TP converted to margin %: (0.60)*(2/102)*10*100 ~= 11.76
    assert call["take_profit_pct"] == pytest.approx(11.7647, rel=1e-3)


@pytest.mark.asyncio
async def test_mr_skips_when_stale():
    ex = _executor(_mr_cfg(), _ctx(fresh=False))
    seen = _spy(ex)
    await ex._try_trade(list(ex._state.values())[0], _overbought(), phase="batch")
    assert len(ex._accounts.calls) == 0
    assert ("skipped", "mr_regime_stale") in seen


@pytest.mark.asyncio
async def test_mr_skips_when_mean_unavailable():
    ctx = ScanContext(btc={("1h", 14): {"regime": "ranging", "vol_value": 1.0, "unavailable": False}},
                      means={}, prices={"BTCUSDT": 102.0}, computed_at=datetime.now(timezone.utc))
    ex = _executor(_mr_cfg(), ctx)
    seen = _spy(ex)
    await ex._try_trade(list(ex._state.values())[0], _overbought(), phase="batch")
    assert len(ex._accounts.calls) == 0
    assert ("skipped", "mr_mean_unavailable") in seen


@pytest.mark.asyncio
async def test_mr_long_rejected_without_ack():
    # oversold buy extreme -> long fade; long enabled but no ack row => skip
    cfg = _mr_cfg(mr_long_enabled=True)
    ctx = _ctx(price=98.0, mean=100.0)   # entry below mean => long fade
    ex = _executor(cfg, ctx, db=_AckDB(row=None))
    seen = _spy(ex)
    signal = {"status": "completed", "ticker": "BTC", "direction": "buy", "score": 8, "id": "r1"}
    await ex._try_trade(list(ex._state.values())[0], signal, phase="batch")
    assert len(ex._accounts.calls) == 0
    assert ("skipped", "mr_long_unacknowledged") in seen


@pytest.mark.asyncio
async def test_mr_long_allowed_with_fresh_ack():
    cfg = _mr_cfg(mr_long_enabled=True, mr_leverage=10, mr_capital_pct=2.0, mr_max_trades=2)
    ctx = _ctx(price=98.0, mean=100.0)
    db = _AckDB(row={"acked_leverage": 10, "acked_capital_pct": 2.0, "acked_max_trades": 2})
    ex = _executor(cfg, ctx, db=db)
    signal = {"status": "completed", "ticker": "BTC", "direction": "buy", "score": 8, "id": "r1"}
    await ex._try_trade(list(ex._state.values())[0], signal, phase="batch")
    assert len(ex._accounts.calls) == 1
    assert ex._accounts.calls[0]["signal_direction"] == "long"


@pytest.mark.asyncio
async def test_mr_long_rejected_when_ack_stale_after_escalation():
    # acked at leverage 5, now config wants leverage 20 => ack invalid
    cfg = _mr_cfg(mr_long_enabled=True, mr_leverage=20)
    ctx = _ctx(price=98.0, mean=100.0)
    db = _AckDB(row={"acked_leverage": 5, "acked_capital_pct": 2.0, "acked_max_trades": 2})
    ex = _executor(cfg, ctx, db=db)
    seen = _spy(ex)
    signal = {"status": "completed", "ticker": "BTC", "direction": "buy", "score": 8, "id": "r1"}
    await ex._try_trade(list(ex._state.values())[0], signal, phase="batch")
    assert len(ex._accounts.calls) == 0
    assert ("skipped", "mr_long_unacknowledged") in seen
