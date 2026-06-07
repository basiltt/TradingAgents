"""Integration test for F3 stored-cohort resolution in the scan path (FR-040).

Guards two bugs: (1) the stored trading_accounts.strategy_cohort must influence
routing (FleetCohortView bulk-assign was inert); (2) the resolver must use ONE
batched list_accounts() lookup (not an N+1 per-account get_account loop). Tri-state:
None cfg cohort inherits stored; an explicit per-scan value (incl "trend") overrides.
"""

from __future__ import annotations

import pytest

from backend.services.scanner_service import ScannerService


class _FakeDB:
    def __init__(self, accounts):
        # accounts: list of account dicts (as list_accounts returns)
        self._accounts = list(accounts)
        self.list_calls = 0

    async def list_accounts(self):
        self.list_calls += 1
        return list(self._accounts)


def _svc(accounts):
    return ScannerService(analysis_service=object(), db=_FakeDB(accounts))


@pytest.mark.asyncio
async def test_inherit_uses_stored_mr_cohort():
    # cfg defers (None) -> inherits the account's stored mean_reversion.
    svc = _svc([{"id": "a1", "strategy_cohort": "mean_reversion"}])
    cfgs = [{"account_id": "a1", "strategy_cohort": None}]
    await svc._resolve_account_cohorts(cfgs)
    assert cfgs[0]["strategy_cohort"] == "mean_reversion"


@pytest.mark.asyncio
async def test_explicit_scan_trend_overrides_stored_mr():
    # An EXPLICIT per-scan "trend" beats a stored mean_reversion (the tri-state fix).
    svc = _svc([{"id": "a1", "strategy_cohort": "mean_reversion"}])
    cfgs = [{"account_id": "a1", "strategy_cohort": "trend"}]
    await svc._resolve_account_cohorts(cfgs)
    assert cfgs[0]["strategy_cohort"] == "trend"


@pytest.mark.asyncio
async def test_explicit_scan_mr_preserved_over_stored_trend():
    svc = _svc([{"id": "a1", "strategy_cohort": "trend"}])
    cfgs = [{"account_id": "a1", "strategy_cohort": "mean_reversion"}]
    await svc._resolve_account_cohorts(cfgs)
    assert cfgs[0]["strategy_cohort"] == "mean_reversion"


@pytest.mark.asyncio
async def test_single_query_for_many_configs_no_n_plus_1():
    # 21 configs must trigger exactly ONE list_accounts() call (not 21 get_account).
    accts = [{"id": f"a{i}", "strategy_cohort": "mean_reversion"} for i in range(21)]
    svc = _svc(accts)
    cfgs = [{"account_id": f"a{i}", "strategy_cohort": None} for i in range(21)]
    await svc._resolve_account_cohorts(cfgs)
    assert svc._db.list_calls == 1
    assert all(c["strategy_cohort"] == "mean_reversion" for c in cfgs)


@pytest.mark.asyncio
async def test_missing_account_inherit_resolves_default():
    svc = _svc([])  # no such account
    cfgs = [{"account_id": "ghost", "strategy_cohort": None}]
    await svc._resolve_account_cohorts(cfgs)
    assert cfgs[0]["strategy_cohort"] == "trend"  # no stored -> default, never None


@pytest.mark.asyncio
async def test_db_error_coerces_to_concrete_default():
    class _BoomDB:
        async def list_accounts(self):
            raise RuntimeError("db down")
    svc = ScannerService(analysis_service=object(), db=_BoomDB())
    cfgs = [{"account_id": "a1", "strategy_cohort": None},
            {"account_id": "a2", "strategy_cohort": "mean_reversion"}]
    await svc._resolve_account_cohorts(cfgs)  # no raise
    assert cfgs[0]["strategy_cohort"] == "trend"          # inherit + no data -> default
    assert cfgs[1]["strategy_cohort"] == "mean_reversion"  # explicit preserved


@pytest.mark.asyncio
async def test_no_db_coerces_none_to_default():
    svc = ScannerService(analysis_service=object(), db=None)
    cfgs = [{"account_id": "a1", "strategy_cohort": None}]
    await svc._resolve_account_cohorts(cfgs)
    assert cfgs[0]["strategy_cohort"] == "trend"  # executor never sees None


@pytest.mark.asyncio
async def test_resolved_cohort_reaches_executor_routing():
    # End-to-end through the REAL _try_trade: stored mean_reversion + cfg inherit
    # (None) must, after resolution, make the executor place a MEAN-REVERSION trade
    # (strategy_kind='mean_reversion'). This exercises the actual routing path, not a
    # reimplemented predicate — if routing drifts, the placed strategy_kind changes.
    from datetime import datetime, timezone
    from backend.services.auto_trade_service import AutoTradeExecutor
    from backend.services.scan_context import ScanContext

    class _StubAccounts:
        def __init__(self):
            self.calls = []

        async def get_mark_price(self, account_id, symbol):
            return 102.0

        async def place_trade(self, **kwargs):
            self.calls.append(kwargs)
            return {"trade_id": "t1", "side": kwargs.get("signal_direction")}

    svc = _svc([{"id": "a1", "strategy_cohort": "mean_reversion"}])
    cfgs = [{
        "account_id": "a1", "strategy_cohort": None,          # inherit
        "mean_reversion_enabled": True, "mr_regime": "ranging",
        "min_score": 6, "mr_extreme_min_abs_score": 5.0, "mr_mean_period": 20,
        "mr_mean_interval": "1h", "mr_leverage": 10, "mr_capital_pct": 2.0,
        "mr_target_capture_pct": 60.0, "mr_tight_stop_pct": 6.0, "mr_min_edge_pct": 1.0,
        "mr_short_enabled": True, "mr_long_enabled": False, "mr_max_trades": 2,
        "regime_staleness_minutes": 30,
    }]
    await svc._resolve_account_cohorts(cfgs)
    assert cfgs[0]["strategy_cohort"] == "mean_reversion"

    ex = AutoTradeExecutor(_StubAccounts())
    ex.init_configs(cfgs)
    st = list(ex._state.values())[0]
    st.base_capital = 1000.0
    ex.set_scan_context(ScanContext(
        btc={("1h", 14): {"regime": "ranging", "vol_value": 1.0, "unavailable": False}},
        means={("BTCUSDT", 20, "1h"): 100.0}, prices={"BTCUSDT": 102.0},
        computed_at=datetime.now(timezone.utc)))

    # overbought sell signal -> MR fades to a short toward the mean
    await ex._try_trade(st, {"status": "completed", "ticker": "BTC",
                             "direction": "sell", "score": 8, "id": "r1"}, phase="batch")
    assert len(ex._accounts.calls) == 1
    assert ex._accounts.calls[0]["strategy_kind"] == "mean_reversion"  # routed as MR

