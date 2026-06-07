"""Integration test for F3 stored-cohort resolution in the scan path (FR-040).

The bug this guards: FleetCohortView bulk-assign writes trading_accounts.strategy_cohort,
but the executor only read cfg["strategy_cohort"] (default "trend"), so a stored cohort
never influenced routing. _resolve_account_cohorts merges the stored field in.
"""

from __future__ import annotations

import pytest

from backend.services.scanner_service import ScannerService


class _FakeDB:
    def __init__(self, accounts):
        self._accounts = accounts

    async def get_account(self, account_id):
        return self._accounts.get(account_id)


def _svc(accounts):
    return ScannerService(analysis_service=object(), db=_FakeDB(accounts))


@pytest.mark.asyncio
async def test_stored_mr_cohort_merged_when_scan_default():
    # Account stored as mean_reversion; the per-scan cfg left at the default "trend".
    svc = _svc({"a1": {"id": "a1", "strategy_cohort": "mean_reversion"}})
    cfgs = [{"account_id": "a1", "strategy_cohort": "trend"}]
    await svc._resolve_account_cohorts(cfgs)
    assert cfgs[0]["strategy_cohort"] == "mean_reversion"  # stored field now drives routing


@pytest.mark.asyncio
async def test_scan_explicit_mr_preserved_over_stored_trend():
    svc = _svc({"a1": {"id": "a1", "strategy_cohort": "trend"}})
    cfgs = [{"account_id": "a1", "strategy_cohort": "mean_reversion"}]
    await svc._resolve_account_cohorts(cfgs)
    assert cfgs[0]["strategy_cohort"] == "mean_reversion"


@pytest.mark.asyncio
async def test_missing_account_leaves_cfg_untouched():
    svc = _svc({})  # no such account
    cfgs = [{"account_id": "ghost", "strategy_cohort": "mean_reversion"}]
    await svc._resolve_account_cohorts(cfgs)
    assert cfgs[0]["strategy_cohort"] == "mean_reversion"  # never downgraded


@pytest.mark.asyncio
async def test_db_error_does_not_raise_or_downgrade():
    class _BoomDB:
        async def get_account(self, account_id):
            raise RuntimeError("db down")
    svc = ScannerService(analysis_service=object(), db=_BoomDB())
    cfgs = [{"account_id": "a1", "strategy_cohort": "mean_reversion"}]
    await svc._resolve_account_cohorts(cfgs)  # no raise
    assert cfgs[0]["strategy_cohort"] == "mean_reversion"


@pytest.mark.asyncio
async def test_no_db_is_noop():
    svc = ScannerService(analysis_service=object(), db=None)
    cfgs = [{"account_id": "a1", "strategy_cohort": "trend"}]
    await svc._resolve_account_cohorts(cfgs)
    assert cfgs[0]["strategy_cohort"] == "trend"


@pytest.mark.asyncio
async def test_resolved_cohort_reaches_executor_routing():
    # End-to-end: a stored mean_reversion cohort (scan cfg at default "trend") must,
    # after resolution + init_configs, make the executor treat the account as MR.
    from backend.services.auto_trade_service import AutoTradeExecutor

    svc = _svc({"a1": {"id": "a1", "strategy_cohort": "mean_reversion"}})
    cfgs = [{"account_id": "a1", "strategy_cohort": "trend",
             "mean_reversion_enabled": True, "mr_regime": "ranging"}]
    await svc._resolve_account_cohorts(cfgs)

    ex = AutoTradeExecutor(object())
    ex.init_configs(cfgs)
    st = list(ex._state.values())[0]
    cohort = st.config.get("strategy_cohort")
    is_mr_account = cohort == "mean_reversion" and bool(st.config.get("mean_reversion_enabled"))
    assert cohort == "mean_reversion"
    assert is_mr_account is True  # the executor's own is_mr_account predicate

