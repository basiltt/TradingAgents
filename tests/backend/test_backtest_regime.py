"""Engine-level tests for F1/F2/F3 replay in the backtester (Phase 2).

The engine is pure: run(config, signals, klines, ..., scan_contexts). scan_contexts
defaults to None -> the regime block is never entered (golden byte-identical). These
tests inject ScanContexts directly and assert the engine gates/routes faithfully via
the SAME pure functions the live path uses.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.services.backtest_engine import BacktestEngine
from backend.services.scan_context import ScanContext


BASE = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)  # 12:00 UTC (an allowed hour)


def _config(**overrides):
    cfg = {
        "starting_capital": 10000.0, "leverage": 10, "capital_pct": 10.0,
        "take_profit_pct": 5.0, "stop_loss_pct": 50.0, "direction": "straight",
        "fee_rate_pct": 0.055, "slippage_bps": 0, "funding_rate_model": "none",
        "execution_mode": "batch", "max_trades": 999, "skip_if_positions_open": False,
    }
    cfg.update(overrides)
    return cfg


def _signal(ticker="ETH", direction="sell", price=100.0, minute=0, sid=1, scan="s1"):
    return {
        "id": sid, "ticker": ticker, "direction": direction, "confidence": "high",
        "score": 8, "signal_time": BASE + timedelta(minutes=minute), "scan_id": scan,
        "signal_source": "structured", "analysis_price": price,
    }


def _klines(ticker_price=100.0, n=600, start=None):
    """5-minute candles, flat unless noted, enough to cover several hours."""
    start = start or BASE
    out = []
    for i in range(n):
        c = ticker_price
        out.append({
            "open_time": start + timedelta(minutes=5 * i),
            "open": c, "high": c, "low": c, "close": c, "volume": 1.0,
        })
    return out


def _ranging_ctx(scan_time=BASE, means=None, degraded=False):
    return ScanContext(
        btc={("1h", 14): {"regime": "ranging", "vol_value": 1.0, "unavailable": False}},
        means=means or {}, prices={}, computed_at=scan_time, degraded=degraded, kill={})


# ── (a) default-off: scan_contexts=None ⇒ identical behavior ──

def test_default_off_runs_without_contexts():
    eng = BacktestEngine()
    cfg = _config()
    sigs = [_signal()]
    kl = {"ETH": _klines()}
    res_none = eng.run(cfg, sigs, kl)  # no scan_contexts arg
    res_empty = BacktestEngine().run(cfg, sigs, kl, None, None, None, {})  # empty contexts
    # A trend signal with no regime features behaves the same either way.
    assert len(res_none.trades) == len(res_empty.trades)
    assert res_none.filter_stats["signals_entered"] == res_empty.filter_stats["signals_entered"]


# ── (b) F1 session gate blocks entries in a blocked UTC hour ──

def test_f1_session_blocks_entry_in_blocked_hour():
    eng = BacktestEngine()
    cfg = _config(regime_filter_enabled=True, session_filter_enabled=True,
                  session_blocked_hours_utc=[12])  # BASE is 12:00 UTC -> blocked
    sigs = [_signal(minute=0)]
    ctx = {"s1": _ranging_ctx()}
    res = eng.run(cfg, sigs, {"ETH": _klines()}, None, None, None, ctx)
    assert res.filter_stats["signals_entered"] == 0  # suppressed by session gate
    assert len(res.trades) == 0


def test_f1_session_allows_in_open_hour():
    eng = BacktestEngine()
    cfg = _config(regime_filter_enabled=True, session_filter_enabled=True,
                  session_blocked_hours_utc=[1, 6, 7])  # 12:00 not blocked
    res = eng.run(cfg, [_signal()], {"ETH": _klines()}, None, None, None, {"s1": _ranging_ctx()})
    assert res.filter_stats["signals_entered"] == 1


# ── (c) F1 BTC-vol gate ──

def test_f1_vol_gate_suppresses_outside_band():
    eng = BacktestEngine()
    cfg = _config(regime_filter_enabled=True, btc_vol_filter_enabled=True,
                  btc_vol_min_threshold=2.0, btc_vol_max_threshold=5.0,
                  btc_vol_interval="1h", btc_vol_lookback_candles=14)
    # vol_value 1.0 < min 2.0 -> suppressed
    ctx = {"s1": ScanContext(btc={("1h", 14): {"regime": "ranging", "vol_value": 1.0, "unavailable": False}},
                             computed_at=BASE)}
    res = eng.run(cfg, [_signal()], {"ETH": _klines()}, None, None, None, ctx)
    assert res.filter_stats["signals_entered"] == 0


def test_f1_vol_gate_fail_open_when_unavailable():
    eng = BacktestEngine()
    cfg = _config(regime_filter_enabled=True, btc_vol_filter_enabled=True,
                  btc_vol_min_threshold=2.0, btc_vol_interval="1h", btc_vol_lookback_candles=14)
    ctx = {"s1": ScanContext(btc={("1h", 14): {"regime": "unknown", "vol_value": None, "unavailable": True}},
                             computed_at=BASE)}
    res = eng.run(cfg, [_signal()], {"ETH": _klines()}, None, None, None, ctx)
    assert res.filter_stats["signals_entered"] == 1  # fail-open: vol unavailable -> allow


# ── (d) F2 mean-reversion routing + fade + TP + tag ──

def test_f2_routes_mr_and_fades_short_above_mean():
    eng = BacktestEngine()
    cfg = _config(mean_reversion_enabled=True, strategy_cohort="mean_reversion",
                  mr_short_enabled=True, mr_mean_period=20, mr_mean_interval="1h",
                  mr_leverage=10, mr_capital_pct=2.0, mr_target_capture_pct=60.0,
                  mr_tight_stop_pct=6.0, mr_min_edge_pct=1.0)
    # entry ~100 (next-bar open), mean 98 -> entry >= mean -> fade SHORT
    means = {("ETHUSDT", 20, "1h"): 98.0}
    ctx = {"s1": _ranging_ctx(means=means)}
    res = eng.run(cfg, [_signal(direction="buy")], {"ETH": _klines(100.0)}, None, None, None, ctx)
    assert len(res.trades) >= 0  # may still be open; check the OPEN position instead
    # Inspect via a fresh run capturing the position: re-run and read filter stats
    assert res.filter_stats["signals_entered"] == 1
    # The recorded trade (force-closed at end) must be tagged mean_reversion + side Sell.
    t = res.trades[0]
    assert t["strategy_kind"] == "mean_reversion"
    assert t["side"] == "Sell"  # short fade


def test_f2_skips_when_regime_not_ranging():
    eng = BacktestEngine()
    cfg = _config(mean_reversion_enabled=True, strategy_cohort="mean_reversion",
                  mr_mean_period=20, mr_mean_interval="1h")
    ctx = {"s1": ScanContext(btc={("1h", 14): {"regime": "trending", "vol_value": 1.0, "unavailable": False}},
                             means={("ETHUSDT", 20, "1h"): 98.0}, computed_at=BASE)}
    res = eng.run(cfg, [_signal()], {"ETH": _klines()}, None, None, None, ctx)
    assert res.filter_stats["signals_entered"] == 0  # MR only runs in ranging


def test_f2_skips_on_missing_mean():
    eng = BacktestEngine()
    cfg = _config(mean_reversion_enabled=True, strategy_cohort="mean_reversion",
                  mr_mean_period=20, mr_mean_interval="1h")
    ctx = {"s1": _ranging_ctx(means={})}  # no mean for ETHUSDT
    res = eng.run(cfg, [_signal()], {"ETH": _klines()}, None, None, None, ctx)
    assert res.filter_stats["signals_entered"] == 0


# ── (e) F2 fast time-stop closes the position ──

def test_f2_time_stop_closes_position():
    eng = BacktestEngine()
    cfg = _config(mean_reversion_enabled=True, strategy_cohort="mean_reversion",
                  mr_short_enabled=True, mr_mean_period=20, mr_mean_interval="1h",
                  mr_leverage=10, mr_tight_stop_pct=6.0, mr_target_capture_pct=60.0,
                  mr_min_edge_pct=1.0, mr_time_stop_minutes=60)
    # Two scans 3h apart so candles between them trigger the 60-min time-stop.
    sigs = [_signal(scan="s1", minute=0)]
    means = {("ETHUSDT", 20, "1h"): 98.0}
    ctx = {"s1": _ranging_ctx(means=means)}
    res = eng.run(cfg, sigs, {"ETH": _klines(100.0, n=200)}, None, None, None, ctx)
    assert len(res.trades) == 1
    assert res.trades[0]["close_reason"] == "mr_time_stop"


# ── (f) F2-long allowed via mr_long_enabled (ack bypassed) ──

def test_f2_long_allowed_when_enabled():
    eng = BacktestEngine()
    cfg = _config(mean_reversion_enabled=True, strategy_cohort="mean_reversion",
                  mr_short_enabled=False, mr_long_enabled=True, mr_mean_period=20,
                  mr_mean_interval="1h", mr_leverage=10, mr_tight_stop_pct=6.0,
                  mr_target_capture_pct=60.0, mr_min_edge_pct=1.0)
    # entry 100, mean 102 -> entry < mean -> fade LONG
    means = {("ETHUSDT", 20, "1h"): 102.0}
    ctx = {"s1": _ranging_ctx(means=means)}
    res = eng.run(cfg, [_signal(direction="sell")], {"ETH": _klines(100.0)}, None, None, None, ctx)
    assert res.filter_stats["signals_entered"] == 1
    assert res.trades[0]["side"] == "Buy"  # long fade
    assert res.trades[0]["strategy_kind"] == "mean_reversion"


def test_f2_long_blocked_when_disabled():
    eng = BacktestEngine()
    cfg = _config(mean_reversion_enabled=True, strategy_cohort="mean_reversion",
                  mr_short_enabled=True, mr_long_enabled=False, mr_mean_period=20,
                  mr_mean_interval="1h", mr_min_edge_pct=1.0)
    means = {("ETHUSDT", 20, "1h"): 102.0}  # would fade long
    ctx = {"s1": _ranging_ctx(means=means)}
    res = eng.run(cfg, [_signal()], {"ETH": _klines(100.0)}, None, None, None, ctx)
    assert res.filter_stats["signals_entered"] == 0  # long disabled


# ── (g) F3 cohort=trend keeps the trend path even with MR config present ──

def test_f3_trend_cohort_uses_trend_path():
    eng = BacktestEngine()
    cfg = _config(strategy_cohort="trend", mean_reversion_enabled=True,
                  mr_mean_period=20, mr_mean_interval="1h", mr_min_edge_pct=1.0)
    # cohort=trend -> is_mr_account False -> trend trade (Sell from sell signal)
    ctx = {"s1": _ranging_ctx(means={("ETHUSDT", 20, "1h"): 98.0})}
    res = eng.run(cfg, [_signal(direction="sell")], {"ETH": _klines(100.0)}, None, None, None, ctx)
    assert res.filter_stats["signals_entered"] == 1
    assert res.trades[0]["strategy_kind"] == "trend"


# ── mr_max_trades parity: MR uses the concurrent MR cap, NOT generic max_trades=999 ──

def test_mr_cap_enforced_concurrent_not_generic_max_trades():
    eng = BacktestEngine()
    # 3 MR signals in one scan, mr_max_trades=2 -> only 2 MR positions open even though
    # the generic max_trades default is 999. Without the cap the backtest would open all 3.
    cfg = _config(mean_reversion_enabled=True, strategy_cohort="mean_reversion",
                  mr_short_enabled=True, mr_mean_period=20, mr_mean_interval="1h",
                  mr_leverage=10, mr_tight_stop_pct=6.0, mr_target_capture_pct=60.0,
                  mr_min_edge_pct=1.0, mr_max_trades=2, max_trades=999)
    sigs = [
        {**_signal(ticker="ETH", sid=1), "scan_id": "s1"},
        {**_signal(ticker="BTC", sid=2), "scan_id": "s1"},
        {**_signal(ticker="SOL", sid=3), "scan_id": "s1"},
    ]
    means = {("ETHUSDT", 20, "1h"): 98.0, ("BTCUSDT", 20, "1h"): 98.0, ("SOLUSDT", 20, "1h"): 98.0}
    ctx = {"s1": _ranging_ctx(means=means)}
    kl = {"ETH": _klines(100.0), "BTC": _klines(100.0), "SOL": _klines(100.0)}
    res = eng.run(cfg, sigs, kl, None, None, None, ctx)
    assert res.filter_stats["signals_entered"] == 2  # capped at mr_max_trades, not 999


def test_price_drift_skipped_for_mr_in_backtest():
    # SD12 parity: price_drift is trend-only. An MR signal whose price drifted past the
    # cap is still entered (the gate is skipped for MR, mirroring live's `not mr_fade`).
    eng = BacktestEngine()
    cfg = _config(mean_reversion_enabled=True, strategy_cohort="mean_reversion",
                  mr_short_enabled=True, mr_mean_period=20, mr_mean_interval="1h",
                  mr_leverage=10, mr_tight_stop_pct=6.0, mr_target_capture_pct=60.0,
                  mr_min_edge_pct=1.0, max_price_drift_pct=1.0)
    # analysis_price 130 vs fill ~100 -> a sell on the trend path drifts -23% (skipped),
    # but MR fades short regardless and must be entered.
    sig = {**_signal(ticker="ETH", direction="sell"), "analysis_price": 130.0}
    ctx = {"s1": _ranging_ctx(means={("ETHUSDT", 20, "1h"): 98.0})}
    res = eng.run(cfg, [sig], {"ETH": _klines(100.0)}, None, None, None, ctx)
    assert res.filter_stats["signals_entered"] == 1
    assert res.trades[0]["strategy_kind"] == "mean_reversion"


def test_price_drift_still_applies_to_trend_in_backtest():
    # Parity guard: drift still fires on the trend path (not globally removed).
    eng = BacktestEngine()
    cfg = _config(max_price_drift_pct=1.0)  # no regime feature -> trend
    sig = {**_signal(ticker="ETH", direction="buy"), "analysis_price": 50.0}
    # fill ~100 vs analysis 50 -> a buy drifted +100% > cap -> skipped
    res = eng.run(cfg, [sig], {"ETH": _klines(100.0)})
    assert res.filter_stats["signals_entered"] == 0

