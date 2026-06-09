"""Tests for engine close rules: liquidation, funding, time-based, multi-scan, cycle lock."""

import pytest
from datetime import datetime, timezone, timedelta


def _make_config(**overrides):
    base = {
        "starting_capital": 10000.0, "leverage": 20, "capital_pct": 5.0,
        "take_profit_pct": 500.0, "stop_loss_pct": 500.0, "direction": "straight",
        "fee_rate_pct": 0.055, "slippage_bps": 0, "execution_mode": "batch",
        "max_trades": 999, "skip_if_positions_open": False, "min_score": 0.0,
        "confidence_filter": "any", "signal_sides": "both", "max_same_direction": None,
        "max_same_sector": None, "symbol_blacklist": None, "symbol_whitelist": None,
        "max_signal_age_minutes": None, "max_price_drift_pct": None,
        "adaptive_blacklist_enabled": False, "fill_to_max_trades": False,
        "target_goal_type": None, "target_goal_value": None, "simulation_interval": "5m",
        "max_drawdown_pct": 100.0, "smart_drawdown_close": False,
        "breakeven_timeout_hours": None, "max_trade_duration_hours": None,
        "trailing_profit_pct": None, "close_on_profit_pct": None,
        "funding_rate_model": "none", "funding_rate_fixed_pct": 0.01,
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


class TestLiquidation:
    """Test liquidation close rule (Task 3.7)."""

    def test_long_liquidation_on_extreme_drop(self):
        """A wide requested SL is CLAMPED to fire before liquidation (matching live),
        so an extreme adverse drop closes via the clamped 'sl' for a real loss — not
        liquidation. AI-CONTEXT: pre-clamp this asserted 'liquidation' (the raw 25%
        SL at 20x sat beyond the ~4.5% liq band). trading_rules.clamp_sl_move_pct_to_
        liquidation now pulls the stop inside that band (4.05%), so it triggers first
        — the live-accurate outcome. Liquidation-with-an-SL is now unreachable by
        design (the clamp guarantees sl_price is inside the liquidation band)."""
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        # 20x leverage → liq ~4.5% below entry = 47750. The requested 25%-move SL is
        # clamped to ~4.05% (0.9× liq distance), so it fires before liquidation.
        config = _make_config(leverage=20, stop_loss_pct=500.0, take_profit_pct=500.0)
        signals = [_make_signal()]

        base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        klines = {"BTCUSDT": [
            {"open_time": base_time, "open": 50000.0, "high": 50100.0, "low": 49900.0, "close": 50000.0, "volume": 100.0},
            # Crash below the clamped SL / liquidation band.
            {"open_time": base_time + timedelta(minutes=5), "open": 50000.0, "high": 50000.0, "low": 47000.0, "close": 47500.0, "volume": 100.0},
        ]}

        result = engine.run(config, signals, klines)
        assert len(result.trades) == 1
        assert result.trades[0]["close_reason"] == "sl"
        assert result.trades[0]["pnl"] < 0  # real loss, clamped before liquidation

    def test_sl_wins_when_closer_than_liquidation(self):
        """When SL is between entry and liq, SL fires (not liquidation)."""
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        # Tight SL at 50% (2.5% price move = 48750) — closer to entry than liq (47750)
        config = _make_config(leverage=20, stop_loss_pct=50.0, take_profit_pct=500.0)
        signals = [_make_signal()]

        base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        klines = {"BTCUSDT": [
            {"open_time": base_time, "open": 50000.0, "high": 50100.0, "low": 49900.0, "close": 50000.0, "volume": 100.0},
            # Drop hits both SL (48750) and liq (47750) — SL is closer, wins
            {"open_time": base_time + timedelta(minutes=5), "open": 50000.0, "high": 50000.0, "low": 47000.0, "close": 47500.0, "volume": 100.0},
        ]}

        result = engine.run(config, signals, klines)
        assert len(result.trades) == 1
        assert result.trades[0]["close_reason"] == "sl"  # SL wins, controlled loss


class TestFundingRate:
    """Test funding rate application (Task 3.8)."""

    def test_long_pays_funding_reduces_equity(self):
        """Long position pays funding — final equity is LOWER with funding than without."""
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        # Flat price so the ONLY difference between runs is funding
        klines = {"BTCUSDT": [
            {"open_time": base_time + timedelta(hours=h),
             "open": 50000.0, "high": 50000.0, "low": 50000.0, "close": 50000.0, "volume": 100.0}
            for h in range(11)  # 00:00 to 10:00 — crosses 08:00 funding boundary
        ]}
        signals = [_make_signal()]

        # Run WITHOUT funding
        config_no_funding = _make_config(
            funding_rate_model="none",
            take_profit_pct=500.0, stop_loss_pct=500.0,
            max_trade_duration_hours=10.0,
        )
        result_none = engine.run(config_no_funding, [_make_signal()], klines)

        # Run WITH funding (long pays at 08:00 boundary)
        config_funding = _make_config(
            funding_rate_model="fixed_8h",
            funding_rate_fixed_pct=0.01,  # 0.01% per 8h
            take_profit_pct=500.0, stop_loss_pct=500.0,
            max_trade_duration_hours=10.0,
        )
        result_funding = engine.run(config_funding, [_make_signal()], klines)

        # Final equity WITH funding must be LOWER (long pays positive funding)
        equity_none = result_none.equity_curve[-1]["equity"]
        equity_funding = result_funding.equity_curve[-1]["equity"]
        assert equity_funding < equity_none, \
            f"Funding should reduce equity: {equity_funding} should be < {equity_none}"

        # Expected funding ~= qty × price × 0.0001 at one 08:00 boundary
        # qty = 10000*5%*20/50000 = 0.2 BTC; funding = 0.2*50000*0.0001 = $1.0
        diff = equity_none - equity_funding
        assert 0.5 < diff < 2.0, f"Funding diff {diff} not in expected range"


class TestTimeBasedRules:
    """Test MAX_DURATION and BREAKEVEN_TIMEOUT (Task 3.6)."""

    def test_max_duration_force_closes(self):
        """MAX_DURATION closes position after elapsed hours."""
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        config = _make_config(
            max_trade_duration_hours=2.0,
            take_profit_pct=500.0, stop_loss_pct=500.0,
        )
        signals = [_make_signal()]

        base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        klines = {"BTCUSDT": [
            {"open_time": base_time + timedelta(minutes=i * 30),
             "open": 50000.0, "high": 50100.0, "low": 49900.0, "close": 50000.0, "volume": 100.0}
            for i in range(8)  # 0 to 3.5 hours
        ]}

        result = engine.run(config, signals, klines)
        assert len(result.trades) == 1
        assert result.trades[0]["close_reason"] == "max_duration"

    def test_breakeven_timeout_modifies_tp(self):
        """BREAKEVEN_TIMEOUT modifies TP to breakeven after timeout (doesn't force-close)."""
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        # Breakeven at 1h. After that, TP moves to ~breakeven (entry × 1.0005).
        config = _make_config(
            breakeven_timeout_hours=1.0,
            take_profit_pct=500.0,  # original wide TP
            stop_loss_pct=500.0,
            max_trade_duration_hours=5.0,  # backstop
        )
        signals = [_make_signal()]

        base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        # Price rises slightly above breakeven after 1h → new TP catches it
        klines = {"BTCUSDT": [
            {"open_time": base_time, "open": 50000.0, "high": 50100.0, "low": 49900.0, "close": 50000.0, "volume": 100.0},
            {"open_time": base_time + timedelta(minutes=30), "open": 50000.0, "high": 50100.0, "low": 49900.0, "close": 50000.0, "volume": 100.0},
            # After 1h → breakeven TP set (~50025) on this candle (time rules run after TP/SL)
            {"open_time": base_time + timedelta(minutes=90), "open": 50000.0, "high": 50010.0, "low": 50000.0, "close": 50005.0, "volume": 100.0},
            # Next candle: price rises to 50100 → new breakeven TP (50025) is hit
            {"open_time": base_time + timedelta(minutes=120), "open": 50005.0, "high": 50100.0, "low": 50000.0, "close": 50050.0, "volume": 100.0},
        ]}

        result = engine.run(config, signals, klines)
        # Position should close via TP at the BREAKEVEN level (~50025), NOT max_duration
        # This proves the breakeven TP modification fired (original TP was 500% = ~75000)
        assert len(result.trades) == 1
        assert result.trades[0]["close_reason"] == "tp"
        # Exit price should be near breakeven (50025), far below original wide TP
        assert result.trades[0]["exit_price"] < 50100, \
            f"Exit {result.trades[0]['exit_price']} should be near breakeven, proving TP was modified"

    def test_breakeven_not_applied_without_timeout(self):
        """Without breakeven_timeout, the same klines do NOT close via tp (control case)."""
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        # NO breakeven_timeout — wide TP stays at 500%, won't be hit by small price rise
        config = _make_config(
            take_profit_pct=500.0, stop_loss_pct=500.0,
            max_trade_duration_hours=5.0,
        )
        signals = [_make_signal()]

        base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        klines = {"BTCUSDT": [
            {"open_time": base_time, "open": 50000.0, "high": 50100.0, "low": 49900.0, "close": 50000.0, "volume": 100.0},
            {"open_time": base_time + timedelta(minutes=30), "open": 50000.0, "high": 50100.0, "low": 49900.0, "close": 50000.0, "volume": 100.0},
            {"open_time": base_time + timedelta(minutes=90), "open": 50000.0, "high": 50010.0, "low": 50000.0, "close": 50005.0, "volume": 100.0},
            {"open_time": base_time + timedelta(minutes=120), "open": 50005.0, "high": 50100.0, "low": 50000.0, "close": 50050.0, "volume": 100.0},
        ]}

        result = engine.run(config, signals, klines)
        # Without breakeven, wide TP not hit → closes via max_duration or backtest_end
        assert len(result.trades) == 1
        assert result.trades[0]["close_reason"] != "tp", \
            "Without breakeven_timeout, the small price rise should NOT hit the wide 500% TP"


class TestMultiSymbolTimeline:
    """Test unified chronological timeline across multiple symbols."""

    def test_interleaved_timestamps_carry_forward_prices(self):
        """Two symbols with offset timestamps — equity uses carried-forward prices."""
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        config = _make_config(
            max_trades=5,
            take_profit_pct=500.0, stop_loss_pct=500.0,
        )
        signals = [
            _make_signal(ticker="BTCUSDT", id=1, analysis_price=50000.0),
            _make_signal(ticker="ETHUSDT", id=2, score=7, analysis_price=3000.0),
        ]

        base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        # BTC candles at :00, :10 ; ETH candles at :05, :15 (interleaved)
        klines = {
            "BTCUSDT": [
                {"open_time": base_time, "open": 50000.0, "high": 50100.0, "low": 49900.0, "close": 50000.0, "volume": 100.0},
                {"open_time": base_time + timedelta(minutes=10), "open": 50000.0, "high": 50500.0, "low": 50000.0, "close": 50300.0, "volume": 100.0},
            ],
            "ETHUSDT": [
                {"open_time": base_time, "open": 3000.0, "high": 3010.0, "low": 2990.0, "close": 3000.0, "volume": 100.0},
                {"open_time": base_time + timedelta(minutes=5), "open": 3000.0, "high": 3050.0, "low": 3000.0, "close": 3030.0, "volume": 100.0},
                {"open_time": base_time + timedelta(minutes=15), "open": 3030.0, "high": 3060.0, "low": 3020.0, "close": 3040.0, "volume": 100.0},
            ],
        }

        result = engine.run(config, signals, klines)
        # Both positions open and force-close at end (no TP/SL hit)
        # Verify no crash, both symbols processed
        assert result.filter_stats["signals_entered"] == 2
        # Both should force-close at backtest end
        assert len(result.trades) == 2
        symbols = {t["symbol"] for t in result.trades}
        assert symbols == {"BTCUSDT", "ETHUSDT"}


class TestForceCloseAtEnd:
    """Test force-close at backtest end (Task 3.10)."""

    def test_open_position_force_closed_at_end(self):
        """Position still open at end of data → force-closed with backtest_end reason."""
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        config = _make_config(take_profit_pct=500.0, stop_loss_pct=500.0)
        signals = [_make_signal()]

        base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        # Flat price — no TP/SL hit, position stays open
        klines = {"BTCUSDT": [
            {"open_time": base_time + timedelta(minutes=i * 5),
             "open": 50000.0, "high": 50050.0, "low": 49950.0, "close": 50000.0, "volume": 100.0}
            for i in range(5)
        ]}

        result = engine.run(config, signals, klines)
        assert len(result.trades) == 1
        assert result.trades[0]["close_reason"] == "backtest_end"
        # Warning about force-close
        assert any("force_closed" in w for w in result.warnings)


class TestCycleLock:
    """Test cycle lock (Task 3.9)."""

    def test_skip_if_positions_open_blocks_new_scan(self):
        """When skip_if_positions_open=True and position open, next scan is skipped."""
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        config = _make_config(
            skip_if_positions_open=True,
            take_profit_pct=500.0, stop_loss_pct=500.0,
        )
        base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        # Two scans: scan1 opens BTC, scan2 (later) should be BLOCKED
        signals = [
            _make_signal(ticker="BTCUSDT", id=1, scan_id="scan1",
                         signal_time=base_time),
            _make_signal(ticker="ETHUSDT", id=2, scan_id="scan2", score=7,
                         signal_time=base_time + timedelta(minutes=10), analysis_price=3000.0),
        ]
        klines = {
            "BTCUSDT": [
                {"open_time": base_time + timedelta(minutes=i * 5),
                 "open": 50000.0, "high": 50050.0, "low": 49950.0, "close": 50000.0, "volume": 100.0}
                for i in range(6)
            ],
            "ETHUSDT": [
                {"open_time": base_time + timedelta(minutes=10 + i * 5),
                 "open": 3000.0, "high": 3010.0, "low": 2990.0, "close": 3000.0, "volume": 100.0}
                for i in range(4)
            ],
        }

        result = engine.run(config, signals, klines)
        # Only BTC should have a position (ETH scan blocked by cycle lock)
        symbols_traded = {t["symbol"] for t in result.trades}
        # ETH was blocked, only BTC entered
        assert "ETHUSDT" not in symbols_traded or result.filter_stats["signals_entered"] == 1


class TestMultiScan:
    """Test multi-scan chronological processing."""

    def test_two_scans_processed_in_order(self):
        """Two scans at different times both process their signals."""
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        config = _make_config(take_profit_pct=500.0, stop_loss_pct=500.0, max_trades=5)
        base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        # Scan1 at 00:00 (BTC), Scan2 at 01:00 (ETH) — both should process
        signals = [
            _make_signal(ticker="BTCUSDT", id=1, scan_id="scan1", signal_time=base_time),
            _make_signal(ticker="ETHUSDT", id=2, scan_id="scan2", score=7,
                         signal_time=base_time + timedelta(hours=1), analysis_price=3000.0),
        ]
        klines = {
            "BTCUSDT": [
                {"open_time": base_time + timedelta(minutes=i * 5),
                 "open": 50000.0, "high": 50050.0, "low": 49950.0, "close": 50000.0, "volume": 100.0}
                for i in range(24)  # 2 hours of data
            ],
            "ETHUSDT": [
                {"open_time": base_time + timedelta(hours=1) + timedelta(minutes=i * 5),
                 "open": 3000.0, "high": 3010.0, "low": 2990.0, "close": 3000.0, "volume": 100.0}
                for i in range(12)  # 1 hour of data
            ],
        }

        result = engine.run(config, signals, klines)
        # Both scans processed (skip_if_positions_open=False default)
        assert result.filter_stats["signals_entered"] == 2
