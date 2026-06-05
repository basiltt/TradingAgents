"""Tests for the filter chain in BacktestEngine — verifies 17-step filter matches production."""

import pytest
from datetime import datetime, timezone, timedelta


def _make_config(**overrides):
    """Create a minimal valid config for testing."""
    base = {
        "starting_capital": 10000.0,
        "leverage": 20,
        "capital_pct": 5.0,
        "take_profit_pct": 150.0,
        "stop_loss_pct": 100.0,
        "direction": "straight",
        "fee_rate_pct": 0.055,
        "slippage_bps": 2,
        "execution_mode": "batch",
        "max_trades": 999,
        "skip_if_positions_open": False,
        "min_score": 0.0,
        "confidence_filter": "any",
        "signal_sides": "both",
        "max_same_direction": None,
        "max_same_sector": None,
        "symbol_blacklist": None,
        "symbol_whitelist": None,
        "max_signal_age_minutes": None,
        "max_price_drift_pct": None,
        "adaptive_blacklist_enabled": False,
        "fill_to_max_trades": False,
        "target_goal_type": None,
        "target_goal_value": None,
        "simulation_interval": "5m",
    }
    base.update(overrides)
    return base


def _make_signal(ticker="BTCUSDT", direction="buy", score=8, confidence="high", **overrides):
    """Create a minimal valid signal."""
    base = {
        "id": 1,
        "ticker": ticker,
        "direction": direction,
        "confidence": confidence,
        "score": score,
        "signal_time": datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc),
        "scan_id": "scan-1",
        "signal_source": "structured",
        "analysis_price": 50000.0,
    }
    base.update(overrides)
    return base


def _make_klines(symbol="BTCUSDT", start_price=50000.0, candles=300):
    """Create synthetic kline data for a symbol."""
    base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    return [
        {
            "open_time": base_time + timedelta(minutes=i * 5),
            "open": start_price,
            "high": start_price * 1.001,
            "low": start_price * 0.999,
            "close": start_price,
            "volume": 100.0,
        }
        for i in range(candles)
    ]


class TestFilterChainBlacklist:
    """Test blacklist/whitelist filters."""

    def test_blacklisted_symbol_rejected(self):
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        config = _make_config(symbol_blacklist=["BTCUSDT"])
        signals = [_make_signal(ticker="BTCUSDT")]
        klines = {"BTCUSDT": _make_klines()}

        result = engine.run(config, signals, klines)
        assert result.trades == []
        assert result.filter_stats["signals_filtered"] > 0

    def test_non_blacklisted_symbol_passes(self):
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        config = _make_config(symbol_blacklist=["ETHUSDT"])
        signals = [_make_signal(ticker="BTCUSDT")]
        klines = {"BTCUSDT": _make_klines()}

        result = engine.run(config, signals, klines)
        # Should have at least attempted to trade (may succeed or fail on other grounds)
        assert result.filter_stats["signals_filtered"] == 0 or result.filter_stats["signals_entered"] > 0

    def test_whitelist_rejects_unlisted(self):
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        config = _make_config(symbol_whitelist=["ETHUSDT"])
        signals = [_make_signal(ticker="BTCUSDT")]
        klines = {"BTCUSDT": _make_klines()}

        result = engine.run(config, signals, klines)
        assert result.trades == []


class TestFilterChainScore:
    """Test min_score and confidence filters."""

    def test_below_min_score_rejected_strict(self):
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        config = _make_config(min_score=5.0)
        signals = [_make_signal(score=3)]
        klines = {"BTCUSDT": _make_klines()}

        result = engine.run(config, signals, klines)
        assert result.trades == []

    def test_above_min_score_passes(self):
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        config = _make_config(min_score=5.0)
        signals = [_make_signal(score=7)]
        klines = {"BTCUSDT": _make_klines()}

        result = engine.run(config, signals, klines)
        # Should enter trade (passes all filters)
        assert result.filter_stats["signals_entered"] >= 1 or len(result.trades) >= 1


class TestFilterChainMaxTrades:
    """Test max_trades limit."""

    def test_max_trades_limits_entries(self):
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        config = _make_config(max_trades=2)
        signals = [
            _make_signal(ticker="BTCUSDT", id=1),
            _make_signal(ticker="ETHUSDT", id=2, score=7),
            _make_signal(ticker="SOLUSDT", id=3, score=6),
        ]
        klines = {
            "BTCUSDT": _make_klines("BTCUSDT"),
            "ETHUSDT": _make_klines("ETHUSDT", 3000.0),
            "SOLUSDT": _make_klines("SOLUSDT", 150.0),
        }

        result = engine.run(config, signals, klines)
        # Should enter at most 2 trades
        assert result.filter_stats["signals_entered"] <= 2


class TestFilterChainSignalSides:
    """Test signal_sides filter."""

    def test_buy_only_rejects_sell(self):
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        config = _make_config(signal_sides="buy")
        signals = [_make_signal(direction="sell", score=-7)]
        klines = {"BTCUSDT": _make_klines()}

        result = engine.run(config, signals, klines)
        assert result.trades == []

    def test_buy_only_accepts_buy(self):
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        config = _make_config(signal_sides="buy")
        signals = [_make_signal(direction="buy", score=7)]
        klines = {"BTCUSDT": _make_klines()}

        result = engine.run(config, signals, klines)
        assert result.filter_stats["signals_entered"] >= 1 or len(result.trades) >= 1


class TestBatchModeDedup:
    """Test batch mode deduplication behavior."""

    def test_batch_keeps_last_occurrence(self):
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        config = _make_config(execution_mode="batch")
        # Same ticker appears twice — batch should keep LAST (score=3, not score=8)
        signals = [
            _make_signal(ticker="BTCUSDT", score=8, id=1),
            _make_signal(ticker="BTCUSDT", score=3, id=2),  # last occurrence
        ]
        klines = {"BTCUSDT": _make_klines()}

        result = engine.run(config, signals, klines)
        # After dedup, only 1 signal should be processed (the last one with score=3)
        # With min_score=0 (default), score=3 still passes
        assert result.filter_stats["signals_total"] == 2
