"""Tests for build_scan_context precompute orchestration (Phase 1 TASK-1.4)."""

from datetime import datetime, timezone

import pytest

from backend.services.market_data import build_scan_context


def _now():
    return datetime(2026, 6, 7, 12, 0, 0, tzinfo=timezone.utc)


def _flat_klines(n, price=100.0):
    return [{"open": price, "high": price, "low": price, "close": price, "volume": 1.0, "open_time": i}
            for i in range(n)]


class _Fetcher:
    def __init__(self, klines_per_call=40):
        self.calls = []
        self._n = klines_per_call

    async def __call__(self, symbol, interval, depth):
        self.calls.append((symbol, interval, depth))
        return _flat_klines(max(self._n, depth))


def _cfg(**kw):
    base = {"account_id": "a"}
    base.update(kw)
    return base


@pytest.mark.asyncio
async def test_precompute_skipped_when_all_off():
    f = _Fetcher()
    ctx = await build_scan_context([_cfg()], [], now=_now(), kill={}, fetcher=f)
    assert f.calls == []                 # no fetches
    assert ctx.degraded is False
    assert ctx.btc == {} and ctx.means == {}


@pytest.mark.asyncio
async def test_empty_path_carries_kill_dict():
    # R3-F1: even on the no-precompute path, the kill dict is carried.
    ctx = await build_scan_context([_cfg()], [], now=_now(), kill={"__all__": True}, fetcher=_Fetcher())
    assert ctx.is_killed("f2") is True


@pytest.mark.asyncio
async def test_btc_classified_when_vol_filter_on():
    f = _Fetcher()
    cfg = _cfg(regime_filter_enabled=True, btc_vol_filter_enabled=True,
               btc_vol_interval="1h", btc_vol_lookback_candles=14)
    ctx = await build_scan_context([cfg], [], now=_now(), kill={}, fetcher=f)
    assert ctx.routing_regime("1h", 14) == "ranging"   # flat market
    # fetch depth is required_depth(14) = 2*14+1 = 29 (SD1a, avoids degenerate atr_ratio)
    assert f.calls[0] == ("BTCUSDT", "1h", 29)


@pytest.mark.asyncio
async def test_mr_cohort_with_vol_filter_off_still_classifies_regime():
    # PR1-6: an MR-cohort account with btc_vol_filter OFF must still get a regime.
    f = _Fetcher()
    cfg = _cfg(strategy_cohort="mean_reversion", mean_reversion_enabled=True,
               btc_vol_filter_enabled=False, btc_vol_interval="1h", btc_vol_lookback_candles=14)
    ctx = await build_scan_context([cfg], [], now=_now(), kill={}, fetcher=f)
    assert ctx.routing_regime("1h", 14) != "unknown"   # regime was classified


@pytest.mark.asyncio
async def test_btc_memoized_by_tuple_across_configs():
    f = _Fetcher()
    # two MR-cohort accounts sharing the same (interval, lookback) => 1 BTC fetch
    cfgs = [_cfg(account_id=str(i), strategy_cohort="mean_reversion", mean_reversion_enabled=True,
                 btc_vol_interval="1h", btc_vol_lookback_candles=14) for i in range(3)]
    await build_scan_context(cfgs, [], now=_now(), kill={}, fetcher=f)
    btc_fetches = [c for c in f.calls if c[0] == "BTCUSDT"]
    assert len(btc_fetches) == 1


@pytest.mark.asyncio
async def test_mean_scoped_to_qualifying_symbols_only():
    f = _Fetcher()
    cfg = _cfg(strategy_cohort="mean_reversion", mean_reversion_enabled=True,
               mr_extreme_min_abs_score=5.0, mr_mean_period=20, mr_mean_interval="1h")
    results = [
        {"status": "completed", "ticker": "AAA", "score": 8, "direction": "sell"},   # qualifies
        {"status": "completed", "ticker": "BBB", "score": 2, "direction": "sell"},   # below threshold
        {"status": "completed", "ticker": "CCC", "score": 6, "direction": "buy"},    # qualifies
    ]
    ctx = await build_scan_context([cfg], results, now=_now(), kill={}, fetcher=f)
    mean_fetches = {c[0] for c in f.calls if c[0] != "BTCUSDT"}
    assert mean_fetches == {"AAAUSDT", "CCCUSDT"}   # not BBB
    assert ctx.get_mean("AAAUSDT", 20, "1h") is not None
    assert ctx.get_price("AAAUSDT") is not None


@pytest.mark.asyncio
async def test_precompute_failure_degrades_globally():
    class _Boom:
        async def __call__(self, *a):
            raise RuntimeError("bybit down")
    cfg = _cfg(regime_filter_enabled=True, btc_vol_filter_enabled=True)
    ctx = await build_scan_context([cfg], [], now=_now(), kill={"f1": True}, fetcher=_Boom())
    assert ctx.degraded is True
    assert ctx.is_killed("f1") is True          # kill dict still carried
    assert ctx.routing_regime("1h", 14) == "unknown"
