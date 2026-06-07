"""Regression tests for adversarial review findings (C1, C2, C5)."""

from datetime import datetime, timezone

import pytest

from backend.services.auto_trade_service import AutoTradeExecutor
from backend.services.scan_context import ScanContext


class _StubAccounts:
    def __init__(self):
        self.calls = []

    async def get_mark_price(self, account_id, symbol):
        return 98.0  # below mean => long fade

    async def place_trade(self, **kwargs):
        self.calls.append(kwargs)
        return {"trade_id": f"t{len(self.calls)}", "side": kwargs.get("signal_direction")}


def _executor(cfg, ctx):
    ex = AutoTradeExecutor(_StubAccounts())
    ex.init_configs([cfg])
    for st in ex._state.values():
        st.base_capital = 1000.0
    ex.set_scan_context(ctx)

    async def _fetch(symbol, interval, depth):
        return [{"open": 100, "high": 100, "low": 100, "close": 100, "volume": 1, "open_time": i}
                for i in range(depth + 1)]
    ex.set_mean_fetcher(_fetch)
    return ex


def _spy(ex):
    seen = []
    orig = ex._emit_decision
    ex._emit_decision = lambda *a, **k: (seen.append((a[3], str(a[4]))), orig(*a, **k))[1]
    return seen


def _ranging_ctx(**kw):
    return ScanContext(
        btc={("1h", 14): {"regime": "ranging", "vol_value": 1.0, "unavailable": False}},
        means={}, prices={}, computed_at=datetime.now(timezone.utc), **kw,
    )


def _mr_cfg(**kw):
    base = {"account_id": "a", "strategy_cohort": "mean_reversion", "mean_reversion_enabled": True,
            "mr_regime": "ranging", "min_score": 6, "mr_extreme_min_abs_score": 5.0,
            "mr_mean_period": 20, "mr_mean_interval": "1h", "mr_leverage": 10,
            "mr_capital_pct": 2.0, "mr_target_capture_pct": 60.0, "mr_tight_stop_pct": 6.0,
            "mr_min_edge_pct": 1.0, "mr_short_enabled": True, "mr_long_enabled": True,
            "mr_max_trades": 5, "regime_staleness_minutes": 30}
    base.update(kw)
    return base


def _oversold():
    return {"status": "completed", "ticker": "BTC", "direction": "buy", "score": 8, "id": "r1"}


# ── C1: f2_long kill stops longs, leaves shorts ──

class _AckPool:
    async def fetchrow(self, *a):
        return {"acked_leverage": 10, "acked_capital_pct": 2.0, "acked_max_trades": 5}


class _AckDB:
    pool = _AckPool()


@pytest.mark.asyncio
async def test_c1_f2_long_kill_blocks_long_fade():
    cfg = _mr_cfg()
    ctx = _ranging_ctx(kill={"f2_long": True})
    ex = _executor(cfg, ctx)
    ex._accounts._db = _AckDB()   # a valid ack exists, so only the kill blocks it
    seen = _spy(ex)
    await ex._try_trade(list(ex._state.values())[0], _oversold(), phase="batch")
    assert len(ex._accounts.calls) == 0
    assert ("skipped", "feature_killed") in seen


# ── C5-A: trend account with stray mean_reversion_enabled is NOT kill-gated by f1 ──

@pytest.mark.asyncio
async def test_c5a_trend_with_stray_mr_enabled_not_f1_killed():
    # trend cohort but mean_reversion_enabled=true and the f1 kill is set.
    # Since it's a trend account (cohort=trend), is_mr_account is False, and with no
    # regime_filter_enabled, regime_active is False => the f1 kill does NOT apply.
    cfg = {"account_id": "a", "strategy_cohort": "trend", "mean_reversion_enabled": True,
           "leverage": 20, "capital_pct": 5, "take_profit_pct": 150, "stop_loss_pct": 100,
           "min_score": 6}
    ctx = _ranging_ctx(kill={"f1": True})
    ex = _executor(cfg, ctx)
    await ex._try_trade(list(ex._state.values())[0],
                        {"status": "completed", "ticker": "BTC", "direction": "sell", "score": 8, "id": "r1"},
                        phase="batch")
    assert len(ex._accounts.calls) == 1   # trend trade placed (not killed)
    assert ex._accounts.calls[0]["strategy_kind"] == "trend"


# ── C5-B: mr-cohort with mean_reversion_enabled=false does NOT place MR ──

@pytest.mark.asyncio
async def test_c5b_mr_cohort_disabled_does_not_trade_mr():
    cfg = _mr_cfg(mean_reversion_enabled=False)
    ctx = _ranging_ctx()
    ex = _executor(cfg, ctx)
    # mean_reversion_enabled=false => not an MR account => routes as trend; but cohort
    # is mean_reversion with no trend signal handling beyond normal => it runs the
    # normal trend path. The key assertion: it must NOT place a mean_reversion trade.
    await ex._try_trade(list(ex._state.values())[0],
                        {"status": "completed", "ticker": "BTC", "direction": "sell", "score": 8, "id": "r1"},
                        phase="batch")
    for call in ex._accounts.calls:
        assert call["strategy_kind"] != "mean_reversion"
