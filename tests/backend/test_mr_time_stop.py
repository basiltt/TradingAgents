"""Tests for FR-023: MR per-account time-stop close rule registration."""

from datetime import datetime, timezone

import pytest

from backend.services.auto_trade_service import AutoTradeExecutor
from backend.services.scan_context import ScanContext


class _StubAccounts:
    def __init__(self):
        self.calls = []

    async def get_mark_price(self, account_id, symbol):
        return 102.0

    async def place_trade(self, **kwargs):
        self.calls.append(kwargs)
        return {"trade_id": f"t{len(self.calls)}", "side": kwargs.get("signal_direction")}


class _CloseSvc:
    def __init__(self):
        self.rules = []

    async def create_rule(self, account_id, rule_data):
        self.rules.append(rule_data)
        return {"id": f"rule{len(self.rules)}"}


def _mr_cfg(**kw):
    base = {"account_id": "a", "strategy_cohort": "mean_reversion", "mean_reversion_enabled": True,
            "mr_regime": "ranging", "min_score": 6, "mr_extreme_min_abs_score": 5.0,
            "mr_mean_period": 20, "mr_mean_interval": "1h", "mr_leverage": 10,
            "mr_capital_pct": 2.0, "mr_target_capture_pct": 60.0, "mr_tight_stop_pct": 6.0,
            "mr_min_edge_pct": 1.0, "mr_short_enabled": True, "mr_long_enabled": False,
            "mr_max_trades": 5, "mr_time_stop_minutes": 90, "regime_staleness_minutes": 30}
    base.update(kw)
    return base


def _ctx():
    return ScanContext(
        btc={("1h", 14): {"regime": "ranging", "vol_value": 1.0, "unavailable": False}},
        means={"BTCUSDT": 100.0} and {("BTCUSDT", 20, "1h"): 100.0},
        prices={"BTCUSDT": 102.0}, computed_at=datetime.now(timezone.utc))


def _executor(cfg, close_svc):
    ex = AutoTradeExecutor(_StubAccounts(), close_positions_service=close_svc)
    ex.init_configs([cfg])
    for st in ex._state.values():
        st.base_capital = 1000.0
    ex.set_scan_context(_ctx())
    return ex


def _overbought():
    return {"status": "completed", "ticker": "BTC", "direction": "sell", "score": 8, "id": "r1"}


@pytest.mark.asyncio
async def test_mr_registers_time_stop_close_rule():
    close = _CloseSvc()
    ex = _executor(_mr_cfg(mr_time_stop_minutes=90), close)
    await ex._try_trade(list(ex._state.values())[0], _overbought(), phase="batch")
    assert len(ex._accounts.calls) == 1                     # MR trade placed
    # exactly one MAX_DURATION rule with 90min => 1.5h
    dur_rules = [r for r in close.rules if r["trigger_type"] == "MAX_DURATION"]
    assert len(dur_rules) == 1
    assert float(dur_rules[0]["threshold_value"]) == pytest.approx(1.5)


@pytest.mark.asyncio
async def test_mr_time_stop_float_no_truncation():
    # 5 minutes => 0.0833h must NOT truncate to 0 (NUMERIC threshold_value).
    close = _CloseSvc()
    ex = _executor(_mr_cfg(mr_time_stop_minutes=5), close)
    await ex._try_trade(list(ex._state.values())[0], _overbought(), phase="batch")
    dur = [r for r in close.rules if r["trigger_type"] == "MAX_DURATION"][0]
    assert float(dur["threshold_value"]) == pytest.approx(5 / 60.0)
    assert float(dur["threshold_value"]) > 0


@pytest.mark.asyncio
async def test_mr_duration_rule_registered_once_per_scan():
    # Two MR placements on one account => only ONE account-level duration rule.
    close = _CloseSvc()
    cfg = _mr_cfg(mr_max_trades=5)
    ex = _executor(cfg, close)
    st = list(ex._state.values())[0]
    # add a second qualifying symbol to the context
    ctx = ScanContext(
        btc={("1h", 14): {"regime": "ranging", "vol_value": 1.0, "unavailable": False}},
        means={("BTCUSDT", 20, "1h"): 100.0, ("ETHUSDT", 20, "1h"): 100.0},
        prices={"BTCUSDT": 102.0, "ETHUSDT": 102.0}, computed_at=datetime.now(timezone.utc))
    ex.set_scan_context(ctx)
    await ex._try_trade(st, {"status": "completed", "ticker": "BTC", "direction": "sell", "score": 8, "id": "r1"}, phase="batch")
    await ex._try_trade(st, {"status": "completed", "ticker": "ETH", "direction": "sell", "score": 8, "id": "r2"}, phase="batch")
    assert len(ex._accounts.calls) == 2
    dur_rules = [r for r in close.rules if r["trigger_type"] == "MAX_DURATION"]
    assert len(dur_rules) == 1   # registered once, not per-placement
