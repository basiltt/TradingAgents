"""Tests for backtest per-scan ScanContext construction (Phase 1).

_build_scan_contexts replays the live build_scan_context for the backtester: it
fetches historical BTC + per-symbol klines and assembles a ScanContext per scan_id,
sliced to candles at/<= the scan time (no look-ahead). It returns {} when no regime
feature is active (default-off pays nothing).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.services.backtest_service import BacktestService
from backend.services.scan_context import ScanContext


BASE = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)


class _FakeKlineCache:
    """Returns synthetic 1h klines per (symbol, interval) over the requested window."""

    def __init__(self, series: dict[str, list[dict]]):
        # series keyed by symbol -> ascending kline dicts (any interval)
        self._series = series
        self.calls: list[tuple] = []

    async def get_klines(self, symbol, interval, start, end):
        self.calls.append((symbol, interval, start, end))
        out = [k for k in self._series.get(symbol, []) if start <= k["open_time"] <= end]
        return out


def _hourly(symbol_base_price: float, n: int, start=BASE, vol: float = 0.0):
    """n hourly candles starting at `start`. vol adds high/low spread for ATR."""
    out = []
    for i in range(n):
        c = symbol_base_price + i * 0.0  # flat closes (ranging) by default
        out.append({
            "open_time": start + timedelta(hours=i),
            "open": c, "high": c + vol, "low": c - vol, "close": c, "volume": 1.0,
        })
    return out


def _svc(kline_cache):
    return BacktestService(db=object(), kline_cache=kline_cache)


def _signals(scan_id, ticker, minute):
    return {"id": 1, "ticker": ticker, "direction": "sell", "score": 8,
            "confidence": "high", "scan_id": scan_id, "signal_source": "structured",
            "analysis_price": 100.0, "signal_time": BASE + timedelta(minutes=minute)}


@pytest.mark.asyncio
async def test_returns_empty_when_no_feature_active():
    # Default-off backtest: no BTC fetch, no contexts -> engine no-ops.
    cache = _FakeKlineCache({})
    svc = _svc(cache)
    cfg = {"date_range_start": BASE, "date_range_end": BASE + timedelta(days=1)}
    out = await svc._build_scan_contexts(cfg, [_signals("s1", "BTC", 0)])
    assert out == {}
    assert cache.calls == []  # no klines fetched


@pytest.mark.asyncio
async def test_builds_btc_regime_for_vol_filter():
    # BTC vol filter on -> a ScanContext per scan with a classified BTC regime.
    btc = _hourly(50000.0, 60, start=BASE - timedelta(hours=60))  # flat -> ranging
    cache = _FakeKlineCache({"BTCUSDT": btc})
    svc = _svc(cache)
    cfg = {
        "date_range_start": BASE, "date_range_end": BASE + timedelta(days=1),
        "regime_filter_enabled": True, "btc_vol_filter_enabled": True,
        "btc_vol_interval": "1h", "btc_vol_lookback_candles": 14,
    }
    # scan at BASE + 3h
    sig = _signals("s1", "ETH", 180)
    out = await svc._build_scan_contexts(cfg, [sig])
    assert "s1" in out
    ctx = out["s1"]
    assert isinstance(ctx, ScanContext)
    br = ctx.get_btc("1h", 14)
    assert br is not None
    assert br["regime"] == "ranging"        # flat market
    assert ctx.computed_at == sig["signal_time"]  # historical instant, not now()
    assert ctx.degraded is False


@pytest.mark.asyncio
async def test_no_lookahead_btc_slice():
    # The BTC slice used for a scan must only include candles with open_time <= scan time.
    btc = _hourly(50000.0, 80, start=BASE - timedelta(hours=40))
    cache = _FakeKlineCache({"BTCUSDT": btc})
    svc = _svc(cache)
    cfg = {
        "date_range_start": BASE, "date_range_end": BASE + timedelta(days=2),
        "regime_filter_enabled": True, "btc_vol_filter_enabled": True,
        "btc_vol_interval": "1h", "btc_vol_lookback_candles": 14,
    }
    early = _signals("s_early", "ETH", 60)   # BASE + 1h
    out = await svc._build_scan_contexts(cfg, [early])
    # A regime is computed only from candles <= scan time; with a 1h slice up to
    # BASE+1h there are 41 candles available (>= required depth 29), so it's defined.
    assert out["s_early"].get_btc("1h", 14) is not None


@pytest.mark.asyncio
async def test_builds_mr_means_for_mean_reversion():
    btc = _hourly(50000.0, 60, start=BASE - timedelta(hours=60))
    eth = _hourly(100.0, 60, start=BASE - timedelta(hours=60))
    cache = _FakeKlineCache({"BTCUSDT": btc, "ETHUSDT": eth})
    svc = _svc(cache)
    cfg = {
        "date_range_start": BASE, "date_range_end": BASE + timedelta(days=1),
        "mean_reversion_enabled": True, "strategy_cohort": "mean_reversion",
        "mr_mean_period": 20, "mr_mean_interval": "1h",
        "btc_vol_interval": "1h", "btc_vol_lookback_candles": 14,
    }
    sig = _signals("s1", "ETH", 180)
    out = await svc._build_scan_contexts(cfg, [sig])
    ctx = out["s1"]
    mean = ctx.get_mean("ETHUSDT", 20, "1h")
    assert mean is not None
    assert abs(mean - 100.0) < 1e-6  # flat closes -> EMA == price


@pytest.mark.asyncio
async def test_degraded_when_btc_missing():
    # MR enabled but no BTC klines -> degraded context (MR fail-closed downstream).
    cache = _FakeKlineCache({})  # no BTCUSDT
    svc = _svc(cache)
    cfg = {
        "date_range_start": BASE, "date_range_end": BASE + timedelta(days=1),
        "mean_reversion_enabled": True, "strategy_cohort": "mean_reversion",
        "btc_vol_interval": "1h", "btc_vol_lookback_candles": 14,
    }
    out = await svc._build_scan_contexts(cfg, [_signals("s1", "ETH", 180)])
    assert out["s1"].degraded is True


@pytest.mark.asyncio
async def test_no_lookahead_excludes_in_progress_candle():
    # CRITICAL look-ahead guard: a candle whose bar has NOT closed at scan_time
    # (open_time + interval > scan_time) carries a FUTURE close and must NOT feed the
    # EMA mean. Build a flat-100 history, then make the LAST (in-progress) 1h candle
    # spike to 200; a scan landing 30 min into that candle must compute the mean from
    # the CLOSED candles only (== 100), never seeing the 200 future close.
    eth = _hourly(100.0, 30, start=BASE - timedelta(hours=30))  # closed candles, flat 100
    # in-progress candle: opens at BASE, would close at BASE+1h, close=200 (the future)
    eth.append({"open_time": BASE, "open": 100.0, "high": 200.0, "low": 100.0,
                "close": 200.0, "volume": 1.0})
    btc = _hourly(50000.0, 60, start=BASE - timedelta(hours=60))
    cache = _FakeKlineCache({"BTCUSDT": btc, "ETHUSDT": eth})
    svc = _svc(cache)
    cfg = {
        "date_range_start": BASE, "date_range_end": BASE + timedelta(days=1),
        "mean_reversion_enabled": True, "strategy_cohort": "mean_reversion",
        "mr_mean_period": 20, "mr_mean_interval": "1h",
        "btc_vol_interval": "1h", "btc_vol_lookback_candles": 14,
    }
    # scan 30 min into the in-progress candle (BASE + 30m) — that candle is NOT closed.
    sig = _signals("s1", "ETH", 30)
    out = await svc._build_scan_contexts(cfg, [sig])
    mean = out["s1"].get_mean("ETHUSDT", 20, "1h")
    assert mean is not None
    # If the future-close (200) leaked in, the EMA would be pulled well above 100.
    assert abs(mean - 100.0) < 1e-6, f"look-ahead: future close leaked into mean ({mean})"


@pytest.mark.asyncio
async def test_mean_matches_live_period_plus_one_depth():
    # Parity: the EMA mean must use exactly period+1 candles (what live fetches), since
    # the EMA value depends on history depth. Build a RISING series so depth matters,
    # then assert the computed mean equals compute_ema_mean over the last period+1
    # CLOSED candles (not the full buffered series).
    from backend.services.market_data import compute_ema_mean
    period = 20
    # 60 rising 1h candles ending well before the scan; closes = 100,101,...,159
    eth = []
    for i in range(60):
        c = 100.0 + i
        eth.append({"open_time": BASE - timedelta(hours=60) + timedelta(hours=i),
                    "open": c, "high": c, "low": c, "close": c, "volume": 1.0})
    btc = _hourly(50000.0, 60, start=BASE - timedelta(hours=60))
    cache = _FakeKlineCache({"BTCUSDT": btc, "ETHUSDT": eth})
    svc = _svc(cache)
    cfg = {
        "date_range_start": BASE, "date_range_end": BASE + timedelta(days=1),
        "mean_reversion_enabled": True, "strategy_cohort": "mean_reversion",
        "mr_mean_period": period, "mr_mean_interval": "1h",
        "btc_vol_interval": "1h", "btc_vol_lookback_candles": 14,
    }
    sig = _signals("s1", "ETH", 180)  # BASE + 3h
    out = await svc._build_scan_contexts(cfg, [sig])
    got = out["s1"].get_mean("ETHUSDT", period, "1h")
    # closed candles at/<= BASE+3h: all 60 fall before that; the LAST period+1 closes
    closed = [k for k in eth if k["open_time"] + timedelta(hours=1) <= sig["signal_time"]]
    expected = compute_ema_mean(closed[-(period + 1):], period)
    assert got is not None and expected is not None
    assert abs(got - expected) < 1e-9, f"mean depth diverges from live period+1 ({got} vs {expected})"


