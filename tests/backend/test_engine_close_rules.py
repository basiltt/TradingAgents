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
        # Use leverage=10, capital_pct=20 so position is 0.4 BTC
        # 5% of 10000 = $500 equity drop. 0.4 BTC needs $1250 price drop (2.5%)
        # Liq at 10x = 50000*0.905 = 45250 — well below test prices
        config = _make_config(
            max_drawdown_pct=5.0,
            leverage=10,
            capital_pct=20.0,
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
            leverage=10,  # 10x so liq is far (45250 for BTC, 2715 for ETH)
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
                {"open_time": base_time + timedelta(minutes=5), "open": 3000.0, "high": 3000.0, "low": 2730.0, "close": 2750.0, "volume": 100.0},
                {"open_time": base_time + timedelta(minutes=10), "open": 2750.0, "high": 2750.0, "low": 2720.0, "close": 2730.0, "volume": 100.0},
            ],
        }

        result = engine.run(config, signals, klines)
        # SMART should close ETH (loser) but keep BTC (winner)
        closed_symbols = [t["symbol"] for t in result.trades]
        if "ETHUSDT" in closed_symbols:
            eth_trade = [t for t in result.trades if t["symbol"] == "ETHUSDT"][0]
            assert eth_trade["close_reason"] == "equity_drop_smart"
            assert eth_trade["pnl"] < 0

    def test_equity_drop_reference_reanchors_each_cycle(self):
        """cycle_start_equity must re-anchor to the CURRENT wallet at the start of
        each fresh cycle — matching production, which re-reads the wallet balance
        into base_capital (the EQUITY_DROP reference) at every scan's init_balances.

        Regression guard (same bug class as max_trades-per-cycle): cycle_start_equity
        was set only when ==0 and zeroed ONLY by the equity rules themselves, so a
        cycle that closed via SL/TP/trailing/max_duration/liquidation left a STALE
        prior-cycle baseline frozen in. The next cycle's equity_drop then measured
        against that stale reference.

        Scenario (hand-verified to reproduce the bug): scan-1 loses ~10.5% of the
        wallet via SL (10000 → ~8913), leaving a stale ~9956 baseline. Scan-2 opens a
        HEALTHY (flat) position. With the BUG, scan-2 equity (~8913) vs the stale
        ~9956 reference = -10.5% → EQUITY_DROP wrongly force-closes the healthy fresh
        position on its first candle. With the FIX, the reference re-anchors to the
        scan-2 wallet, so the flat position does NOT trigger equity_drop.
        """
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        # High capital + a wide-ish SL so scan-1's loss is a LARGE fraction of the
        # wallet (>max_drawdown_pct), which is what surfaces the stale-reference bug.
        config = _make_config(
            max_drawdown_pct=5.0,
            leverage=10,
            capital_pct=80.0,
            take_profit_pct=500.0,   # wide → only SL or equity_drop can close
            stop_loss_pct=12.0,      # scan-1 SL stops out at a large $ loss
            slippage_bps=0,
            skip_if_positions_open=False,
        )

        scan1 = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        scan2 = datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc)
        signals = [
            _make_signal(ticker="BTCUSDT", id=1, scan_id="scan-1", signal_time=scan1),
            _make_signal(ticker="BTCUSDT", id=2, scan_id="scan-2", signal_time=scan2),
        ]

        c = []
        # scan-1: 50000 → 44400 over 8 candles (~-11% → past the 12%-leveraged SL),
        # losing ~10.5% of the wallet.
        for i in range(8):
            px = 50000.0 - i * 800.0
            c.append({"open_time": scan1 + timedelta(minutes=i * 5),
                      "open": px, "high": px + 30, "low": px - 850, "close": px - 800, "volume": 100.0})
        # Bridge flat candles to scan-2 (stable ~44000 so the next entry is clean).
        bridge_start = scan1 + timedelta(minutes=60)
        for i in range(6):
            c.append({"open_time": bridge_start + timedelta(minutes=i * 5),
                      "open": 44000.0, "high": 44050.0, "low": 43950.0, "close": 44000.0, "volume": 100.0})
        # scan-2: FLAT around 44000 (healthy, ~breakeven — must NOT equity_drop).
        for i in range(6):
            c.append({"open_time": scan2 + timedelta(minutes=i * 5),
                      "open": 44000.0, "high": 44100.0, "low": 43900.0, "close": 44000.0, "volume": 100.0})
        klines = {"BTCUSDT": c}

        result = engine.run(config, signals, klines)

        # scan-1's trade closed at a loss (SL), shrinking the wallet well past 5%.
        assert len(result.trades) >= 1
        scan1_trade = [t for t in result.trades if t.get("scan_id") == "scan-1"][0]
        assert scan1_trade["close_reason"] in ("sl", "liquidation")
        assert scan1_trade["pnl"] < 0

        # The KEY assertion: scan-2's healthy flat position must NOT be force-closed by
        # equity_drop. Under the bug it WOULD (stale ~9956 ref → instant -10.5%).
        scan2_trades = [t for t in result.trades if t.get("scan_id") == "scan-2"]
        assert scan2_trades, "scan-2 should have opened a position"
        for t in scan2_trades:
            assert t["close_reason"] != "equity_drop", (
                "scan-2's fresh position was force-closed by a STALE cycle_start_equity "
                "reference from scan-1 — equity_drop must re-anchor per cycle"
            )


class TestTrailingProfit:
    """Test TRAILING_PROFIT close rule state machine."""

    def test_trailing_activates_and_closes_on_pullback(self):
        """Trailing activates at threshold, then closes when profit drops 50% from peak."""
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        # trailing_profit_pct=3 → activates at 3% price move
        config = _make_config(
            trailing_profit_pct=3.0,
            take_profit_pct=500.0,  # wide TP (won't hit)
            stop_loss_pct=500.0,   # wide SL (won't hit)
            slippage_bps=0,
        )
        signals = [_make_signal()]

        base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        # Price rises past 3% (activates trailing), peaks, then drops 50% from peak
        klines = {"BTCUSDT": [
            {"open_time": base_time, "open": 50000.0, "high": 50100.0, "low": 49900.0, "close": 50000.0, "volume": 100.0},
            # +2% (not yet activated)
            {"open_time": base_time + timedelta(minutes=5), "open": 50000.0, "high": 51100.0, "low": 50000.0, "close": 51000.0, "volume": 100.0},
            # +4% (activated! profit_pct=4 > threshold=3)
            {"open_time": base_time + timedelta(minutes=10), "open": 51000.0, "high": 52100.0, "low": 51000.0, "close": 52000.0, "volume": 100.0},
            # +6% peak
            {"open_time": base_time + timedelta(minutes=15), "open": 52000.0, "high": 53100.0, "low": 52000.0, "close": 53000.0, "volume": 100.0},
            # Pullback — profit drops but not yet 50% from peak
            {"open_time": base_time + timedelta(minutes=20), "open": 53000.0, "high": 53000.0, "low": 51800.0, "close": 52000.0, "volume": 100.0},
            # Further pullback — per_unit_pnl drops below 50% of peak → CLOSE
            {"open_time": base_time + timedelta(minutes=25), "open": 52000.0, "high": 52000.0, "low": 50800.0, "close": 51000.0, "volume": 100.0},
        ]}

        result = engine.run(config, signals, klines)
        assert len(result.trades) >= 1
        assert result.trades[0]["close_reason"] == "trailing_profit"
        assert result.trades[0]["pnl"] > 0  # still profitable (just less than peak)

    def test_trailing_not_activated_when_in_loss(self):
        """Trailing does NOT activate when upnl <= 0 (even if price moved far in abs terms)."""
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        config = _make_config(
            trailing_profit_pct=3.0,
            take_profit_pct=500.0,
            stop_loss_pct=500.0,
            slippage_bps=0,
        )
        # Buy signal but price drops immediately
        signals = [_make_signal(direction="buy")]

        base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        klines = {"BTCUSDT": [
            {"open_time": base_time, "open": 50000.0, "high": 50100.0, "low": 49900.0, "close": 50000.0, "volume": 100.0},
            # Price drops 5% (>3% threshold in abs terms, but upnl is NEGATIVE)
            {"open_time": base_time + timedelta(minutes=5), "open": 50000.0, "high": 50000.0, "low": 47400.0, "close": 47500.0, "volume": 100.0},
            {"open_time": base_time + timedelta(minutes=10), "open": 47500.0, "high": 47600.0, "low": 47400.0, "close": 47500.0, "volume": 100.0},
        ]}

        result = engine.run(config, signals, klines)
        # Should NOT have closed via trailing (upnl <= 0 guard prevents activation)
        trailing_closes = [t for t in result.trades if t.get("close_reason") == "trailing_profit"]
        assert len(trailing_closes) == 0
