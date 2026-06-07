"""End-to-end: one scan with all 3 regime features enabled (Phase 5 T-03/R4-14).

Validates gate COMPOSITION through the real executor — kill-switch, cohort routing,
F1 session/vol, and F2 placement interacting over a mixed signal set with an injected
ScanContext. Also the degraded-scan AD1 scenario (F1 open + F2 closed at once).
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


def _executor(cfg, ctx):
    ex = AutoTradeExecutor(_StubAccounts())
    ex.init_configs([cfg])
    for st in ex._state.values():
        st.base_capital = 1000.0
    ex.set_scan_context(ctx)
    return ex


def _spy(ex):
    seen = []
    orig = ex._emit_decision

    def s(account_id, phase, symbol, decision, reason_code, result, **detail):
        seen.append((result.get("ticker"), decision, str(reason_code)))
        return orig(account_id, phase, symbol, decision, reason_code, result, **detail)

    ex._emit_decision = s
    return seen


@pytest.mark.asyncio
async def test_e2e_mr_cohort_ranging_places_and_skips():
    # MR-cohort account in ranging regime: overbought extreme places a SHORT fade;
    # a below-threshold-score signal is excluded by the MR extreme filter.
    cfg = {"account_id": "a", "strategy_cohort": "mean_reversion", "mean_reversion_enabled": True,
           "mr_regime": "ranging", "min_score": 6, "mr_extreme_min_abs_score": 5.0,
           "mr_mean_period": 20, "mr_mean_interval": "1h", "mr_leverage": 10,
           "mr_capital_pct": 2.0, "mr_target_capture_pct": 60.0, "mr_tight_stop_pct": 6.0,
           "mr_min_edge_pct": 1.0, "mr_short_enabled": True, "mr_long_enabled": False,
           "regime_staleness_minutes": 30}
    now = datetime.now(timezone.utc)
    ctx = ScanContext(
        btc={("1h", 14): {"regime": "ranging", "vol_value": 1.0, "unavailable": False}},
        means={("AAAUSDT", 20, "1h"): 100.0},
        prices={"AAAUSDT": 102.0},     # above mean => short fade
        computed_at=now,
    )
    ex = _executor(cfg, ctx)
    results = [
        {"status": "completed", "ticker": "AAA", "direction": "sell", "score": 8, "id": "r1"},  # extreme -> fade
        {"status": "completed", "ticker": "BBB", "direction": "sell", "score": 2, "id": "r2"},  # below extreme
    ]
    for r in results:
        await ex._try_trade(list(ex._state.values())[0], r, phase="batch")
    # AAA placed as MR short; BBB skipped (mean unavailable since not a qualifying symbol)
    assert len(ex._accounts.calls) == 1
    assert ex._accounts.calls[0]["strategy_kind"] == "mean_reversion"
    assert ex._accounts.calls[0]["signal_direction"] == "short"


@pytest.mark.asyncio
async def test_e2e_trend_cohort_with_f1_session_block():
    # trend account, F1 session filter on, current hour blocked => suppressed.
    now_hour = datetime.now(timezone.utc).hour
    cfg = {"account_id": "a", "strategy_cohort": "trend", "leverage": 20, "capital_pct": 5,
           "take_profit_pct": 150, "stop_loss_pct": 100, "min_score": 6,
           "regime_filter_enabled": True, "session_filter_enabled": True,
           "session_blocked_hours_utc": [now_hour]}
    ctx = ScanContext.empty(degraded=False)
    ex = _executor(cfg, ctx)
    seen = _spy(ex)
    await ex._try_trade(list(ex._state.values())[0],
                        {"status": "completed", "ticker": "BTC", "direction": "sell", "score": 8, "id": "r1"},
                        phase="batch")
    assert len(ex._accounts.calls) == 0
    assert ("BTC", "skipped", "session_filter") in seen


@pytest.mark.asyncio
async def test_e2e_degraded_scan_f1_open_f2_closed():
    # AD1: a single degraded ScanContext => trend (F1) proceeds, MR (F2) excluded.
    ctx = ScanContext.empty(degraded=True)
    signal = {"status": "completed", "ticker": "BTC", "direction": "sell", "score": 8, "id": "r1"}

    # trend account with F1 enabled (no blocked hours) => fail-open => places
    trend_cfg = {"account_id": "t", "strategy_cohort": "trend", "leverage": 20, "capital_pct": 5,
                 "take_profit_pct": 150, "stop_loss_pct": 100, "min_score": 6,
                 "regime_filter_enabled": True, "btc_vol_filter_enabled": True,
                 "btc_vol_min_threshold": 0.8}
    ex_t = _executor(trend_cfg, ctx)
    await ex_t._try_trade(list(ex_t._state.values())[0], signal, phase="batch")
    assert len(ex_t._accounts.calls) == 1   # F1 fail-open: trend proceeds

    # MR account => degraded regime is 'unknown' => route 'none' => no MR
    mr_cfg = {"account_id": "m", "strategy_cohort": "mean_reversion", "mean_reversion_enabled": True,
              "mr_regime": "ranging", "min_score": 6}
    ex_m = _executor(mr_cfg, ctx)
    seen = _spy(ex_m)
    await ex_m._try_trade(list(ex_m._state.values())[0], signal, phase="batch")
    assert len(ex_m._accounts.calls) == 0   # F2 fail-closed
    assert ("BTC", "skipped", "mr_regime_excluded") in seen
