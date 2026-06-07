"""Regression tests for Step-12c implementation review fixes (IR1-IR7)."""

from datetime import datetime, timezone

import pytest

from backend.services.auto_trade_service import AutoTradeExecutor
from backend.services.scan_context import ScanContext
from backend.services import mean_reversion_math as mr
from backend.services.strategy_reason_codes import ReasonCode


class _StubAccounts:
    def __init__(self):
        self.calls = []

    async def get_mark_price(self, account_id, symbol):
        return 102.0

    async def place_trade(self, **kwargs):
        self.calls.append(kwargs)
        return {"trade_id": f"t{len(self.calls)}", "side": kwargs.get("signal_direction")}


def _mr_cfg(**kw):
    base = {"account_id": "a", "strategy_cohort": "mean_reversion", "mean_reversion_enabled": True,
            "mr_regime": "ranging", "min_score": 6, "mr_extreme_min_abs_score": 5.0,
            "mr_mean_period": 20, "mr_mean_interval": "1h", "mr_leverage": 10,
            "mr_capital_pct": 2.0, "mr_target_capture_pct": 60.0, "mr_tight_stop_pct": 6.0,
            "mr_min_edge_pct": 1.0, "mr_short_enabled": True, "mr_long_enabled": False,
            "mr_max_trades": 2, "regime_staleness_minutes": 30}
    base.update(kw)
    return base


def _ranging_ctx(symbol="BTCUSDT", price=None):
    # NOTE: deliberately NO means/prices -> exercises the lazy fallback (IR1)
    return ScanContext(
        btc={("1h", 14): {"regime": "ranging", "vol_value": 1.0, "unavailable": False}},
        means={}, prices=({symbol: price} if price else {}),
        computed_at=datetime.now(timezone.utc),
    )


def _executor(cfg, ctx, klines=None):
    ex = AutoTradeExecutor(_StubAccounts())
    ex.init_configs([cfg])
    for st in ex._state.values():
        st.base_capital = 1000.0
    ex.set_scan_context(ctx)
    if klines is not None:
        async def _fetch(symbol, interval, depth):
            return klines
        ex.set_mean_fetcher(_fetch)
    return ex


def _flat_klines(n, price):
    return [{"open": price, "high": price, "low": price, "close": price, "volume": 1.0, "open_time": i}
            for i in range(n)]


def _overbought():
    return {"status": "completed", "ticker": "BTC", "direction": "sell", "score": 8, "id": "r1"}


# ── IR1: lazy MR mean makes F2 reachable when context has no precomputed mean ──

@pytest.mark.asyncio
async def test_ir1_lazy_mean_enables_placement():
    # mean=100 from klines, entry=102 mark price => short fade places
    ex = _executor(_mr_cfg(), _ranging_ctx(), klines=_flat_klines(30, 100.0))
    await ex._try_trade(list(ex._state.values())[0], _overbought(), phase="batch")
    assert len(ex._accounts.calls) == 1
    assert ex._accounts.calls[0]["strategy_kind"] == "mean_reversion"


@pytest.mark.asyncio
async def test_ir1_lazy_mean_cached_per_scan():
    ex = _executor(_mr_cfg(), _ranging_ctx(), klines=_flat_klines(30, 100.0))
    count = {"n": 0}

    async def _counting_fetch(symbol, interval, depth):
        count["n"] += 1
        return _flat_klines(30, 100.0)
    ex.set_mean_fetcher(_counting_fetch)
    st = list(ex._state.values())[0]
    await ex._try_trade(st, _overbought(), phase="batch")
    # second attempt on same symbol reuses cache (already_held would also short-circuit,
    # but the cache check happens regardless)
    await ex._lazy_mr_mean("BTCUSDT", 20, "1h")
    assert count["n"] == 1  # fetched once, cached


# ── IR2: strategy_cohort + f1_active persisted ──

@pytest.mark.asyncio
async def test_ir2_cohort_and_f1_active_passed_to_place_trade():
    cfg = _mr_cfg(regime_filter_enabled=True)
    ex = _executor(cfg, _ranging_ctx(), klines=_flat_klines(30, 100.0))
    await ex._try_trade(list(ex._state.values())[0], _overbought(), phase="batch")
    call = ex._accounts.calls[0]
    assert call["strategy_cohort"] == "mean_reversion"
    assert call["f1_active"] is True


# ── IR3: geometry guard uses the capture-scaled placed TP ──

def test_ir3_guard_uses_capture_scaled_tp():
    # entry 102 mean 100 lev 10: full TP ~19.6%, capture 60% => placed TP ~11.76%.
    # An SL of 15% passes the OLD full-capture check (15<19.6) but must FAIL now
    # (15 >= 11.76 placed TP => inverted).
    rc = mr.check_geometry(102.0, 100.0, "short", tight_sl_pct=15.0, leverage=10.0,
                           min_edge_pct=1.0, capture_pct=60.0)
    assert rc == ReasonCode.MR_INVERTED_GEOMETRY


# ── IR6: mr_max_trades enforced as MR position cap ──

@pytest.mark.asyncio
async def test_ir6_mr_max_trades_cap_enforced():
    cfg = _mr_cfg(mr_max_trades=1, max_trades=999)
    ex = _executor(cfg, _ranging_ctx(), klines=_flat_klines(30, 100.0))
    st = list(ex._state.values())[0]
    # pretend one MR position already open
    st.existing_symbols.add("ETHUSDT")
    seen = []
    orig = ex._emit_decision
    ex._emit_decision = lambda *a, **k: (seen.append((a[3], str(a[4]))), orig(*a, **k))[1]
    await ex._try_trade(st, _overbought(), phase="batch")
    assert len(ex._accounts.calls) == 0   # capped at mr_max_trades=1
    assert any(d == "skipped" and r == "max_trades" for d, r in seen)


# ── IR7: SL-vs-liquidation guard ──

def test_ir7_sl_beyond_liquidation_skips():
    # leverage 10 => liquidation ~10% price move. SL price-move = sl_pct/lev/100.
    # sl_pct=95 => 95/10/100 = 9.5% price move >= 0.9*10% => MR_SL_LIQUIDATION.
    # use a wide mean so inverted-geometry doesn't fire first.
    rc = mr.check_geometry(150.0, 100.0, "short", tight_sl_pct=95.0, leverage=10.0,
                           min_edge_pct=1.0, capture_pct=100.0)
    assert rc == ReasonCode.MR_SL_LIQUIDATION
