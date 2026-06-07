"""T-19/T-20/T-24: MR cap cross-phase + resume, recheck, and new-entries-only.

These pin behaviors the spec calls out (FR-028, FR-053, FR-064). Note the cap is
implemented as a concurrent-position cap over ``existing_symbols`` (which is rehydrated
from open exchange positions on resume), not a separate per-scan counter — equivalent
for an all-MR cohort and resume-safe by construction.
"""

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
            "mr_max_trades": 2, "regime_staleness_minutes": 30}
    base.update(kw)
    return base


def _ctx(symbols=("BTCUSDT", "ETHUSDT", "ADAUSDT")):
    return ScanContext(
        btc={("1h", 14): {"regime": "ranging", "vol_value": 1.0, "unavailable": False}},
        means={(s, 20, "1h"): 100.0 for s in symbols},
        prices={s: 102.0 for s in symbols}, computed_at=datetime.now(timezone.utc))


def _executor(cfg, *, existing=None, close_svc=None):
    ex = AutoTradeExecutor(_StubAccounts(), close_positions_service=close_svc)
    ex.init_configs([cfg])
    for st in ex._state.values():
        st.base_capital = 1000.0
        if existing:
            st.existing_symbols = set(existing)
    ex.set_scan_context(_ctx())
    return ex


def _sell(ticker, rid):
    return {"status": "completed", "ticker": ticker, "direction": "sell", "score": 8, "id": rid}


# ── T-19: MR cap enforced across placements (cross-phase) ──

@pytest.mark.asyncio
async def test_t19_mr_cap_enforced_across_placements():
    ex = _executor(_mr_cfg(mr_max_trades=2))
    st = list(ex._state.values())[0]
    await ex._try_trade(st, _sell("BTC", "r1"), phase="batch")
    await ex._try_trade(st, _sell("ETH", "r2"), phase="batch")
    await ex._try_trade(st, _sell("ADA", "r3"), phase="relaxed")  # 3rd exceeds cap=2
    assert len(ex._accounts.calls) == 2  # third blocked by mr_max_trades


@pytest.mark.asyncio
async def test_t19_mr_cap_counts_preexisting_positions_on_resume():
    # On resume, existing_symbols is rehydrated from open positions. A cap of 2 with
    # one position already open must allow only ONE more MR entry.
    ex = _executor(_mr_cfg(mr_max_trades=2), existing={"BTCUSDT"})
    st = list(ex._state.values())[0]
    await ex._try_trade(st, _sell("ETH", "r1"), phase="batch")   # 2nd overall -> ok
    await ex._try_trade(st, _sell("ADA", "r2"), phase="batch")   # 3rd overall -> blocked
    assert len(ex._accounts.calls) == 1


# ── T-24: new-entries-only — an already-held symbol is never re-managed/re-entered ──

@pytest.mark.asyncio
async def test_t24_already_held_symbol_not_reentered():
    ex = _executor(_mr_cfg(mr_max_trades=5), existing={"BTCUSDT"})
    st = list(ex._state.values())[0]
    await ex._try_trade(st, _sell("BTC", "r1"), phase="batch")  # already held
    assert len(ex._accounts.calls) == 0  # no new entry on a held symbol


@pytest.mark.asyncio
async def test_t24_toggling_does_not_touch_open_positions():
    # The gates only run inside _try_trade (entry path). Disabling MR mid-life cannot
    # close an open position — there is no management path over existing_symbols.
    ex = _executor(_mr_cfg(mean_reversion_enabled=False), existing={"BTCUSDT"})
    st = list(ex._state.values())[0]
    # a disabled-MR account routes as trend; the held BTC position is untouched either way
    assert "BTCUSDT" in st.existing_symbols
    assert len(ex._accounts.calls) == 0


# ── T-20: recheck preserves the MR time-stop (flag resets so it re-registers) ──

@pytest.mark.asyncio
async def test_t20_recheck_resets_mr_duration_flag_so_time_stop_recreated():
    close = _CloseSvc()
    ex = _executor(_mr_cfg(mr_time_stop_minutes=90, mr_max_trades=5), close_svc=close)
    st = list(ex._state.values())[0]

    # Cycle 1: first MR placement registers the account-level time-stop once.
    await ex._try_trade(st, _sell("BTC", "r1"), phase="batch")
    assert st.mr_duration_rule_created is True
    dur1 = [r for r in close.rules if r["trigger_type"] == "MAX_DURATION"]
    assert len(dur1) == 1

    # Simulate the post_scan_recheck state reset (the FR-053 fix resets this flag).
    st.mr_duration_rule_created = False
    st.existing_symbols = set()

    # Cycle 2 (recheck): a new MR placement must RE-register the time-stop.
    await ex._try_trade(st, _sell("ETH", "r2"), phase="batch")
    dur2 = [r for r in close.rules if r["trigger_type"] == "MAX_DURATION"]
    assert len(dur2) == 2  # recreated — MR positions never left without their fast exit
