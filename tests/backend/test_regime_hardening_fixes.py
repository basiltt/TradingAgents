"""Regression tests for Step-14 hardening fixes (P1/P2/D2/D4/D5)."""

import inspect

import pytest

from backend.services.scanner_service import ScannerService
from backend.services.trade_repository import TradeRepository


def test_p1_scanner_accepts_and_stores_kline_cache():
    # P1 CRITICAL: the feature was inert because the kline cache was never wired.
    assert "kline_cache" in inspect.signature(ScannerService.__init__).parameters
    s = ScannerService.__new__(ScannerService)
    ScannerService.__init__(s, analysis_service=None, kline_cache="SENTINEL")
    assert s._kline_cache == "SENTINEL"


def test_p1_main_wires_kline_cache():
    import backend.main  # noqa
    src = inspect.getsource(backend.main)
    assert "scanner_service._kline_cache = app.state.kline_cache_service" in src


@pytest.mark.asyncio
async def test_d2_create_trade_rejects_bad_strategy_kind():
    # D2: a bad strategy_kind must raise BEFORE the INSERT (not trip the DB CHECK
    # after a live order exists).
    repo = TradeRepository(db=None)
    with pytest.raises(ValueError, match="strategy_kind"):
        await repo.create_trade(None, account_id="a", symbol="BTCUSDT", side="Buy",
                                qty=1.0, strategy_kind="hacker")
    with pytest.raises(ValueError, match="strategy_cohort"):
        await repo.create_trade(None, account_id="a", symbol="BTCUSDT", side="Buy",
                                qty=1.0, strategy_cohort="hacker")


def test_d4_d5_ack_table_uses_double_precision_and_audit_column():
    from backend.async_persistence import _MIGRATIONS
    mig46 = dict((v, sql) for v, sql in _MIGRATIONS if v == 46)[46]
    assert "acked_capital_pct DOUBLE PRECISION" in mig46   # D4: not REAL
    assert "updated_by TEXT" in mig46                       # D5: audit column


@pytest.mark.asyncio
async def test_p2_mark_price_cached_per_scan():
    # P2: mark price fetched once per symbol per scan (shared across accounts).
    from backend.services.auto_trade_service import AutoTradeExecutor

    class _Accounts:
        def __init__(self):
            self.n = 0

        async def get_mark_price(self, account_id, symbol):
            self.n += 1
            return 100.0

    ex = AutoTradeExecutor(_Accounts())
    ex.init_configs([{"account_id": "a"}])
    p1 = await ex._lazy_mark_price("a", "BTCUSDT")
    p2 = await ex._lazy_mark_price("b", "BTCUSDT")   # different account, same symbol
    assert p1 == p2 == 100.0
    assert ex._accounts.n == 1                         # only one fetch (cached)
    # cache resets on the next scan's init_configs
    ex.init_configs([{"account_id": "a"}])
    await ex._lazy_mark_price("a", "BTCUSDT")
    assert ex._accounts.n == 2
