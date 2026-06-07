"""Integration tests for the regime gates wired into _try_trade (Phase 2/3).

Drives the real AutoTradeExecutor with a stubbed accounts service and an injected
ScanContext, asserting the new gates fire (or don't) per config + context.
"""

from datetime import datetime, timezone

import pytest

from backend.services.auto_trade_service import AutoTradeExecutor
from backend.services.scan_context import ScanContext


class _StubAccounts:
    def __init__(self):
        self.calls = []

    async def get_mark_price(self, account_id, symbol):
        return 100.0

    async def place_trade(self, **kwargs):
        self.calls.append(kwargs)
        return {"trade_id": f"t{len(self.calls)}", "side": kwargs.get("signal_direction")}


def _executor(cfg, ctx=None):
    ex = AutoTradeExecutor(_StubAccounts())
    ex.init_configs([cfg])
    for st in ex._state.values():
        st.base_capital = 1000.0
    if ctx is not None:
        ex.set_scan_context(ctx)
    return ex


def _sell_signal(score=8):
    return {"status": "completed", "ticker": "BTC", "direction": "sell",
            "confidence": "high", "score": score, "id": "r1"}


def _spy(ex):
    seen = []
    orig = ex._emit_decision

    def s(account_id, phase, symbol, decision, reason_code, result, **detail):
        seen.append((decision, str(reason_code)))
        return orig(account_id, phase, symbol, decision, reason_code, result, **detail)

    ex._emit_decision = s
    return seen


@pytest.mark.asyncio
async def test_trend_cohort_unaffected_by_regime_block():
    # trend cohort runs trend in all regimes; with no F1 enabled it should place.
    cfg = {"account_id": "a", "leverage": 20, "capital_pct": 5, "take_profit_pct": 150,
           "stop_loss_pct": 100, "min_score": 6, "strategy_cohort": "trend"}
    ctx = ScanContext(btc={("1h", 14): {"regime": "trending", "vol_value": 1.0, "unavailable": False}},
                      computed_at=datetime.now(timezone.utc))
    ex = _executor(cfg, ctx)
    await ex._try_trade(list(ex._state.values())[0], _sell_signal(), phase="batch")
    assert len(ex._accounts.calls) == 1  # placed


@pytest.mark.asyncio
async def test_f1_session_suppresses_when_in_blocked_hour():
    # Block the current UTC hour -> trend entry suppressed.
    now_hour = datetime.now(timezone.utc).hour
    cfg = {"account_id": "a", "leverage": 20, "capital_pct": 5, "take_profit_pct": 150,
           "stop_loss_pct": 100, "min_score": 6, "strategy_cohort": "trend",
           "regime_filter_enabled": True, "session_filter_enabled": True,
           "session_blocked_hours_utc": [now_hour]}
    ex = _executor(cfg)
    seen = _spy(ex)
    await ex._try_trade(list(ex._state.values())[0], _sell_signal(), phase="batch")
    assert len(ex._accounts.calls) == 0
    assert ("skipped", "session_filter") in seen


@pytest.mark.asyncio
async def test_mr_cohort_excluded_in_trending_regime():
    cfg = {"account_id": "a", "leverage": 20, "capital_pct": 5, "take_profit_pct": 150,
           "stop_loss_pct": 100, "min_score": 6, "strategy_cohort": "mean_reversion",
           "mean_reversion_enabled": True, "mr_regime": "ranging"}
    ctx = ScanContext(btc={("1h", 14): {"regime": "trending", "vol_value": 1.0, "unavailable": False}},
                      computed_at=datetime.now(timezone.utc))
    ex = _executor(cfg, ctx)
    seen = _spy(ex)
    await ex._try_trade(list(ex._state.values())[0], _sell_signal(), phase="batch")
    assert len(ex._accounts.calls) == 0
    assert ("skipped", "mr_regime_excluded") in seen


@pytest.mark.asyncio
async def test_kill_switch_master_suppresses_placement():
    # AC-010: a flipped __all__ kill row blocks a would-be trade.
    cfg = {"account_id": "a", "leverage": 20, "capital_pct": 5, "take_profit_pct": 150,
           "stop_loss_pct": 100, "min_score": 6, "strategy_cohort": "trend",
           "regime_filter_enabled": True, "session_filter_enabled": True,
           "session_blocked_hours_utc": []}
    ctx = ScanContext.empty(degraded=False, kill={"__all__": True})
    ex = _executor(cfg, ctx)
    seen = _spy(ex)
    await ex._try_trade(list(ex._state.values())[0], _sell_signal(), phase="batch")
    assert len(ex._accounts.calls) == 0
    assert ("skipped", "feature_killed") in seen


@pytest.mark.asyncio
async def test_per_feature_kill_f1():
    cfg = {"account_id": "a", "leverage": 20, "capital_pct": 5, "take_profit_pct": 150,
           "stop_loss_pct": 100, "min_score": 6, "strategy_cohort": "trend",
           "regime_filter_enabled": True, "session_filter_enabled": True,
           "session_blocked_hours_utc": []}
    ctx = ScanContext.empty(degraded=False, kill={"f1": True})
    ex = _executor(cfg, ctx)
    await ex._try_trade(list(ex._state.values())[0], _sell_signal(), phase="batch")
    assert len(ex._accounts.calls) == 0  # f1 (trend cohort) killed


def _mr_cfg(**kw):
    base = {"account_id": "a", "strategy_cohort": "mean_reversion", "mean_reversion_enabled": True,
            "mr_regime": "ranging", "min_score": 6, "mr_extreme_min_abs_score": 5.0,
            "mr_mean_period": 20, "mr_mean_interval": "1h", "mr_leverage": 10,
            "mr_capital_pct": 2.0, "mr_target_capture_pct": 60.0, "mr_tight_stop_pct": 6.0,
            "mr_min_edge_pct": 1.0, "mr_short_enabled": True, "mr_long_enabled": False,
            "mr_max_trades": 5, "regime_staleness_minutes": 30}
    base.update(kw)
    return base


def _ranging_ctx(mean=98.0, price=100.0):
    return ScanContext(
        btc={("1h", 14): {"regime": "ranging", "vol_value": 1.0, "unavailable": False}},
        means={("BTCUSDT", 20, "1h"): mean}, prices={"BTCUSDT": price},
        computed_at=datetime.now(timezone.utc))


@pytest.mark.asyncio
async def test_price_drift_skipped_for_mr():
    # SD12: price_drift is trend-only. A sell signal whose price already dropped past
    # the drift cap WOULD be skipped on the trend path — but for an MR fade (side from
    # price-vs-mean, not the signal) it must be SKIPPED and the trade placed.
    cfg = _mr_cfg(max_price_drift_pct=5.0)
    ctx = _ranging_ctx(mean=98.0, price=100.0)  # entry 100 >= mean 98 -> fade short
    ex = _executor(cfg, ctx)
    # analysis_price 130 vs mark 100 -> drift -23% < -5% -> trend path would skip a sell
    sig = {"status": "completed", "ticker": "BTC", "direction": "sell",
           "confidence": "high", "score": 8, "id": "r1", "analysis_price": 130.0}
    await ex._try_trade(list(ex._state.values())[0], sig, phase="batch")
    assert len(ex._accounts.calls) == 1  # MR placed despite the drift (gate skipped)
    assert ex._accounts.calls[0]["strategy_kind"] == "mean_reversion"


@pytest.mark.asyncio
async def test_price_drift_still_applies_to_trend():
    # Parity guard: the drift gate STILL fires on the trend path (not globally removed).
    cfg = {"account_id": "a", "leverage": 20, "capital_pct": 5, "take_profit_pct": 150,
           "stop_loss_pct": 100, "min_score": 6, "strategy_cohort": "trend",
           "max_price_drift_pct": 5.0}
    ex = _executor(cfg)  # no regime context needed for a pure trend signal
    sig = {"status": "completed", "ticker": "BTC", "direction": "sell",
           "confidence": "high", "score": 8, "id": "r1", "analysis_price": 130.0}
    seen = _spy(ex)
    await ex._try_trade(list(ex._state.values())[0], sig, phase="batch")
    assert len(ex._accounts.calls) == 0  # trend trade skipped by drift
    assert ("skipped", "price_drift") in seen
