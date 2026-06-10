"""Phase P2 parity tests: concurrent loaders produce identical results to serial.

The loader optimizations (asyncio.gather over per-symbol get_klines, gathered 1m
drilldown fetch) must be byte-identical to the old sequential loops — only the
wall-clock overlaps. These tests pin that equivalence headless (no DB/network).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from backend.services.backtest_service import BacktestService

UTC = timezone.utc
BASE = datetime(2026, 1, 1, tzinfo=UTC)


class FakeKlineCache:
    """Returns deterministic per-symbol klines; records call order."""

    def __init__(self):
        self.calls = []

    async def get_klines(self, symbol, interval, start, end):
        self.calls.append(symbol)
        # small async yield so concurrency actually interleaves (exposes order bugs)
        await asyncio.sleep(0)
        n = {"BTCUSDT": 3, "ETHUSDT": 2, "SOLUSDT": 4}.get(symbol, 1)
        return [
            {"open_time": BASE + timedelta(minutes=5 * i), "open": 1.0 * i, "high": 1.0,
             "low": 1.0, "close": 1.0 * i, "volume": 1.0}
            for i in range(n)
        ]


def _signals(*tickers):
    return [{"id": i, "ticker": t, "direction": "buy", "signal_time": BASE,
             "scan_id": "s1", "analysis_price": 1.0} for i, t in enumerate(tickers)]


@pytest.mark.asyncio
async def test_load_klines_concurrent_matches_serial():
    """Concurrent _load_klines == an explicit serial load of the same symbols."""
    cache = FakeKlineCache()
    svc = BacktestService(db=None, kline_cache=cache)
    cfg = {"simulation_interval": "5m", "date_range_start": BASE,
           "date_range_end": BASE + timedelta(days=1)}
    signals = _signals("ETHUSDT", "BTCUSDT", "SOLUSDT", "BTCUSDT")  # dup + unsorted

    concurrent = await svc._load_klines(cfg, signals)

    # Reference: serial load over the same sorted unique symbols.
    symbols = sorted({s["ticker"] for s in signals})
    serial = {}
    for sym in symbols:
        serial[sym] = await cache.get_klines(sym, "5m", cfg["date_range_start"], cfg["date_range_end"])

    assert concurrent == serial
    # deterministic key set (sorted unique), regardless of signal order
    assert list(concurrent.keys()) == symbols


@pytest.mark.asyncio
async def test_load_klines_empty_cache_returns_empty():
    svc = BacktestService(db=None, kline_cache=None)
    cfg = {"simulation_interval": "5m", "date_range_start": BASE,
           "date_range_end": BASE + timedelta(days=1)}
    assert await svc._load_klines(cfg, _signals("BTCUSDT")) == {}


@pytest.mark.asyncio
async def test_load_klines_each_symbol_fetched_once():
    """Concurrency must not duplicate or drop a symbol's fetch."""
    cache = FakeKlineCache()
    svc = BacktestService(db=None, kline_cache=cache)
    cfg = {"simulation_interval": "5m", "date_range_start": BASE,
           "date_range_end": BASE + timedelta(days=1)}
    await svc._load_klines(cfg, _signals("BTCUSDT", "ETHUSDT", "BTCUSDT"))
    # 2 unique symbols → exactly 2 fetches (dedup by the sorted-set), no dups.
    assert sorted(cache.calls) == ["BTCUSDT", "ETHUSDT"]
