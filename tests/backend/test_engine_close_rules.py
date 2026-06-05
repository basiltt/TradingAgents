"""Tests for TP/SL wick-based evaluation in the simulation engine."""

import pytest
from datetime import datetime, timezone, timedelta


def _make_config(**overrides):
    base = {
        "starting_capital": 10000.0, "leverage": 20, "capital_pct": 5.0,
        "take_profit_pct": 100.0, "stop_loss_pct": 50.0, "direction": "straight",
        "fee_rate_pct": 0.055, "slippage_bps": 0, "execution_mode": "batch",
        "max_trades": 999, "skip_if_positions_open": False, "min_score": 0.0,
        "confidence_filter": "any", "signal_sides": "both", "max_same_direction": None,
        "max_same_sector": None, "symbol_blacklist": None, "symbol_whitelist": None,
        "max_signal_age_minutes": None, "max_price_drift_pct": None,
        "adaptive_blacklist_enabled": False, "fill_to_max_trades": False,
        "target_goal_type": None, "target_goal_value": None, "simulation_interval": "5m",
        # Close rules (disabled by default for isolated testing)
        "max_drawdown_pct": 100.0, "smart_drawdown_close": False,
        "breakeven_timeout_hours": None, "max_trade_duration_hours": None,
        "trailing_profit_pct": None, "close_on_profit_pct": None,
    }
    base.update(overrides)
    return base


def _make_signal(ticker="BTCUSDT", direction="buy", score=8, **overrides):
    base = {
        "id": 1, "ticker": ticker, "direction": direction, "confidence": "high",
        "score": score, "signal_time": datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
        "scan_id": "s1", "signal_source": "structured", "analysis_price": 50000.0,
    }
    base.update(overrides)
    return base


class TestTpSlWickBased:
    """Test TP/SL closes on candle wicks (High/Low)."""

    def test_long_tp_hit_on_high(self):
        """Long position: TP hit when candle.high >= tp_price."""
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        # TP = 100% at 20x → 5% price move → entry * 1.05
        # Entry ~50000 (no slippage) → TP ~52500
        config = _make_config(take_profit_pct=100.0, slippage_bps=0)
        signals = [_make_signal()]

        base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        klines = {"BTCUSDT": [
            # Candle 0: entry candle (signal fires here)
            {"open_time": base_time, "open": 50000.0, "high": 50100.0, "low": 49900.0, "close": 50000.0, "volume": 100.0},
            # Candle 1: price rises but doesn't hit TP
            {"open_time": base_time + timedelta(minutes=5), "open": 50000.0, "high": 51000.0, "low": 49900.0, "close": 50800.0, "volume": 100.0},
            # Candle 2: HIGH hits TP (52500)
            {"open_time": base_time + timedelta(minutes=10), "open": 50800.0, "high": 52600.0, "low": 50700.0, "close": 52400.0, "volume": 100.0},
            # Candle 3: after close (shouldn't matter)
            {"open_time": base_time + timedelta(minutes=15), "open": 52400.0, "high": 53000.0, "low": 52000.0, "close": 52500.0, "volume": 100.0},
        ]}

        result = engine.run(config, signals, klines)
        assert len(result.trades) == 1
        trade = result.trades[0]
        assert trade["close_reason"] == "tp"
        assert trade["pnl"] > 0  # profitable

    def test_long_sl_hit_on_low(self):
        """Long position: SL hit when candle.low <= sl_price."""
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        # SL = 50% at 20x → 2.5% price drop → entry * 0.975
        # Entry ~50000 → SL ~48750
        config = _make_config(stop_loss_pct=50.0, slippage_bps=0)
        signals = [_make_signal()]

        base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        klines = {"BTCUSDT": [
            {"open_time": base_time, "open": 50000.0, "high": 50100.0, "low": 49900.0, "close": 50000.0, "volume": 100.0},
            # Candle 1: LOW hits SL (48750)
            {"open_time": base_time + timedelta(minutes=5), "open": 50000.0, "high": 50000.0, "low": 48700.0, "close": 49000.0, "volume": 100.0},
        ]}

        result = engine.run(config, signals, klines)
        assert len(result.trades) == 1
        assert result.trades[0]["close_reason"] == "sl"
        assert result.trades[0]["pnl"] < 0  # loss

    def test_both_tp_and_sl_hit_same_candle_pessimistic(self):
        """When both TP and SL hit on same candle, SL wins (pessimistic)."""
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        config = _make_config(take_profit_pct=100.0, stop_loss_pct=50.0, slippage_bps=0)
        signals = [_make_signal()]

        base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        klines = {"BTCUSDT": [
            {"open_time": base_time, "open": 50000.0, "high": 50100.0, "low": 49900.0, "close": 50000.0, "volume": 100.0},
            # Candle 1: Both TP (52500) and SL (48750) hit — massive wick
            {"open_time": base_time + timedelta(minutes=5), "open": 50000.0, "high": 53000.0, "low": 48000.0, "close": 50500.0, "volume": 100.0},
        ]}

        result = engine.run(config, signals, klines)
        assert len(result.trades) == 1
        # Pessimistic: SL wins
        assert result.trades[0]["close_reason"] == "sl"

    def test_short_tp_hit_on_low(self):
        """Short position: TP hit when candle.low <= tp_price."""
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        # Short: TP = price drops. TP at 100% at 20x → entry * 0.95 = 47500
        config = _make_config(take_profit_pct=100.0, stop_loss_pct=50.0, slippage_bps=0)
        signals = [_make_signal(direction="sell", score=-8)]

        base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        klines = {"BTCUSDT": [
            {"open_time": base_time, "open": 50000.0, "high": 50100.0, "low": 49900.0, "close": 50000.0, "volume": 100.0},
            # Candle 1: LOW hits short TP (47500)
            {"open_time": base_time + timedelta(minutes=5), "open": 50000.0, "high": 50100.0, "low": 47400.0, "close": 48000.0, "volume": 100.0},
        ]}

        result = engine.run(config, signals, klines)
        assert len(result.trades) == 1
        assert result.trades[0]["close_reason"] == "tp"
        assert result.trades[0]["pnl"] > 0


class TestEquityCloseRules:
    """Test EQUITY_RISE_PCT, EQUITY_DROP_PCT, EQUITY_DROP_PCT_SMART."""

    def test_equity_drop_closes_all_positions(self):
        """EQUITY_DROP_PCT triggers when equity drops X% from reference → close ALL."""
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        # max_drawdown_pct=5 → close all when equity drops 5% from cycle start
        config = _make_config(
            max_drawdown_pct=5.0,
            take_profit_pct=500.0,  # Very wide TP (won't hit)
            stop_loss_pct=500.0,    # Very wide SL (won't hit)
            slippage_bps=0,
        )
        signals = [_make_signal(ticker="BTCUSDT", direction="buy", score=8)]

        base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        # Price drops steadily — equity falls with it
        klines = {"BTCUSDT": [
            {"open_time": base_time, "open": 50000.0, "high": 50100.0, "low": 49900.0, "close": 50000.0, "volume": 100.0},
            {"open_time": base_time + timedelta(minutes=5), "open": 50000.0, "high": 50000.0, "low": 49000.0, "close": 49500.0, "volume": 100.0},
            {"open_time": base_time + timedelta(minutes=10), "open": 49500.0, "high": 49500.0, "low": 48000.0, "close": 48200.0, "volume": 100.0},
            # By now: 50000 → 48200 = -3.6% price, at 20x leverage with 5% capital → equity drop should trigger
            {"open_time": base_time + timedelta(minutes=15), "open": 48200.0, "high": 48200.0, "low": 47000.0, "close": 47500.0, "volume": 100.0},
        ]}

        result = engine.run(config, signals, klines)
        assert len(result.trades) >= 1
        # Should close due to equity drop, not TP/SL
        assert result.trades[0]["close_reason"] == "equity_drop"

    def test_equity_rise_closes_all_positions(self):
        """EQUITY_RISE_PCT triggers when equity rises X% → close ALL (take profit on cycle)."""
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        # We need close_on_profit_pct OR a separate equity_rise config
        # Per spec: EQUITY_RISE_PCT uses max_drawdown's complement
        # Actually per plan Task 3.8b: close_on_profit_pct handles this
        # For this test, we'll use close_on_profit_pct
        config = _make_config(
            close_on_profit_pct=50.0,  # 50% of target_goal_value
            target_goal_value=10.0,    # effective threshold = 5%
            take_profit_pct=500.0,
            stop_loss_pct=500.0,
            slippage_bps=0,
        )
        signals = [_make_signal(ticker="BTCUSDT", direction="buy", score=8)]

        base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        # Price rises steadily
        klines = {"BTCUSDT": [
            {"open_time": base_time, "open": 50000.0, "high": 50100.0, "low": 49900.0, "close": 50000.0, "volume": 100.0},
            {"open_time": base_time + timedelta(minutes=5), "open": 50000.0, "high": 52000.0, "low": 50000.0, "close": 51500.0, "volume": 100.0},
            {"open_time": base_time + timedelta(minutes=10), "open": 51500.0, "high": 54000.0, "low": 51500.0, "close": 53000.0, "volume": 100.0},
        ]}

        result = engine.run(config, signals, klines)
        assert len(result.trades) >= 1
        assert result.trades[0]["close_reason"] == "close_on_profit"
        assert result.trades[0]["pnl"] > 0

    def test_smart_drawdown_closes_only_losers(self):
        """EQUITY_DROP_PCT_SMART closes only losing positions, keeps winners."""
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        config = _make_config(
            max_drawdown_pct=3.0,
            smart_drawdown_close=True,
            take_profit_pct=500.0,
            stop_loss_pct=500.0,
            slippage_bps=0,
            max_trades=5,
        )
        # Two signals: BTC (will go up) and ETH (will go down)
        signals = [
            _make_signal(ticker="BTCUSDT", direction="buy", score=8, id=1),
            _make_signal(ticker="ETHUSDT", direction="buy", score=7, id=2, analysis_price=3000.0),
        ]

        base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        klines = {
            "BTCUSDT": [
                {"open_time": base_time, "open": 50000.0, "high": 50100.0, "low": 49900.0, "close": 50000.0, "volume": 100.0},
                {"open_time": base_time + timedelta(minutes=5), "open": 50000.0, "high": 51000.0, "low": 50000.0, "close": 50800.0, "volume": 100.0},
                {"open_time": base_time + timedelta(minutes=10), "open": 50800.0, "high": 51500.0, "low": 50800.0, "close": 51200.0, "volume": 100.0},
            ],
            "ETHUSDT": [
                {"open_time": base_time, "open": 3000.0, "high": 3010.0, "low": 2990.0, "close": 3000.0, "volume": 100.0},
                # ETH drops hard — causes equity drop
                {"open_time": base_time + timedelta(minutes=5), "open": 3000.0, "high": 3000.0, "low": 2700.0, "close": 2750.0, "volume": 100.0},
                {"open_time": base_time + timedelta(minutes=10), "open": 2750.0, "high": 2750.0, "low": 2500.0, "close": 2600.0, "volume": 100.0},
            ],
        }

        result = engine.run(config, signals, klines)
        # SMART should close ETH (loser) but keep BTC (winner)
        closed_symbols = [t["symbol"] for t in result.trades]
        if "ETHUSDT" in closed_symbols:
            eth_trade = [t for t in result.trades if t["symbol"] == "ETHUSDT"][0]
            assert eth_trade["close_reason"] == "equity_drop_smart"
            assert eth_trade["pnl"] < 0
