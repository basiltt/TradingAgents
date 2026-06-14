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

    def test_breakeven_closes_all_when_recovered(self):
        """After breakeven time, once total open uPnL >= fee buffer the position is
        force-closed with reason 'breakeven' (not 'tp', not 'max_duration')."""
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        config = _make_config(
            breakeven_timeout_hours=1.0,
            take_profit_pct=500.0, stop_loss_pct=500.0,
            max_trade_duration_hours=5.0,
            leverage=20, capital_pct=5.0, fee_rate_pct=0.055, slippage_bps=0,
        )
        signals = [_make_signal()]
        base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        # Underwater through breakeven time (1h), then recovers at 120min. NOTE: BREAKEVEN_
        # TIMEOUT marks the account on the ADVERSE side of the bar (a long uses the bar LOW,
        # not the close — the engine's conservative live-parity mark so a brief favorable
        # wick can't trigger a mass close live would not confirm). So the recovery candle's
        # LOW must clear entry+buffer: entry 50000, qty 0.2, buffer ≈ 8.2 → need
        # 0.2*(low-50000) >= 8.2 → low >= ~50041. Use low 50100 (uPnL +20 > buffer).
        klines = {"BTCUSDT": [
            {"open_time": base_time, "open": 50000.0, "high": 50000.0, "low": 49900.0, "close": 50000.0, "volume": 100.0},
            {"open_time": base_time + timedelta(minutes=30), "open": 50000.0, "high": 50000.0, "low": 49500.0, "close": 49600.0, "volume": 100.0},
            {"open_time": base_time + timedelta(minutes=90), "open": 49600.0, "high": 49900.0, "low": 49500.0, "close": 49800.0, "volume": 100.0},
            {"open_time": base_time + timedelta(minutes=120), "open": 50100.0, "high": 50200.0, "low": 50100.0, "close": 50150.0, "volume": 100.0},
        ]}
        result = engine.run(config, signals, klines)
        assert len(result.trades) == 1
        assert result.trades[0]["close_reason"] == "breakeven", result.trades[0]["close_reason"]

    def test_breakeven_excludes_mr_timestopped_position_from_upnl_sum(self):
        """A position queued by the MR fast time-stop must be EXCLUDED from the account-
        level breakeven uPnL sum (via the id() set at the breakeven block), so its PnL can't
        pollute the recovery check for the OTHER still-open positions.

        Direct unit test of `_evaluate_time_rules` (an end-to-end kline fixture cannot reach
        this path: the MR time-stop is the ONLY rule that queues a position BEFORE the
        breakeven sum is computed — MAX_DURATION runs AFTER breakeven, so it can never
        pre-exclude anything; see the rule ordering in _evaluate_time_rules).

        Setup: one account, both positions past the 1h breakeven window.
          - MR position (time_stop_minutes=60): a large winner (+200). At elapsed ≥ 60min it
            is queued 'mr_time_stop' FIRST → its id() enters the exclusion set.
          - Trend position: mildly underwater (−~32), alone below its own fee buffer.

        With the exclusion the breakeven sum sees only the trend leg (< buffer) → it does NOT
        close 'breakeven' (it survives this candle). If someone drops the id() exclusion, the
        MR winner's +200 pollutes the sum (≫ buffer) and the trend leg wrongly closes
        'breakeven' — so this test fails, guarding the exclusion. The MR leg itself always
        closes 'mr_time_stop'."""
        from backend.services.backtest_engine import BacktestEngine, Position, SimulationState

        engine = BacktestEngine()
        config = _make_config(
            breakeven_timeout_hours=1.0, max_trade_duration_hours=None,
            leverage=20, fee_rate_pct=0.055, slippage_bps=0,
        )
        base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        # MR winner: entered at t=0, qty 0.2 @ 50000; time-stop 60min (fires at the candle).
        mr_pos = Position(
            symbol="BTCUSDT", side="Buy", entry_price=50000.0, qty=0.2, leverage=20,
            entry_time=base_time, tp_price=300000.0, sl_price=1.0, liq_price=1.0,
            entry_fee=0.0, locked_margin=0.0, strategy_kind="mean_reversion",
            time_stop_minutes=60.0, equity_ref_entry=50000.0,
        )
        # Trend leg: entered at t=0, qty 0.2 @ 3000; mildly underwater at the candle.
        trend_pos = Position(
            symbol="ETHUSDT", side="Buy", entry_price=3000.0, qty=0.2, leverage=20,
            entry_time=base_time, tp_price=30000.0, sl_price=1.0, liq_price=1.0,
            entry_fee=0.0, locked_margin=0.0, strategy_kind="trend",
            equity_ref_entry=3000.0,
        )
        state = SimulationState(wallet_balance=10000.0)
        state.open_positions = [mr_pos, trend_pos]
        # breakeven rule armed at t=0 (account-level), so at the t=120 candle it is elapsed.
        state.breakeven_rule_started_at = base_time
        candle_time = base_time + timedelta(minutes=120)
        # Marks: MR is a clear winner (+200 on the close mark); trend mildly underwater.
        latest_prices = {"BTCUSDT": 51000.0, "ETHUSDT": 2990.0}
        # adverse-side marks (long → low) used by the breakeven sum: keep MR a winner and the
        # trend leg underwater so the trend leg alone can never clear its own buffer.
        breakeven_prices = {"BTCUSDT": 51000.0, "ETHUSDT": 2990.0}

        engine._evaluate_time_rules(
            config, state, candle_time, 0.00055,
            latest_prices=latest_prices, breakeven_prices=breakeven_prices,
        )
        by_symbol = {t["symbol"]: t for t in state.closed_trades}
        # The MR leg closes via its fast time-stop (queued first → excluded from the sum).
        assert by_symbol["BTCUSDT"]["close_reason"] == "mr_time_stop", by_symbol.get("BTCUSDT")
        # The discriminator: the trend leg must NOT ride the excluded MR winner's uPnL into a
        # 'breakeven' close. With the exclusion intact it stays open this candle.
        assert "ETHUSDT" not in by_symbol, (
            f"trend leg wrongly closed: {by_symbol.get('ETHUSDT')}"
        )
        assert any(p.symbol == "ETHUSDT" for p in state.open_positions), "trend leg must stay open"

    def test_breakeven_closes_all_via_account_netting(self):
        """ACCOUNT-LEVEL netting: a winner's uPnL carries an underwater sibling over the
        COMBINED fee buffer so BOTH close 'breakeven' in one candle — even though the
        underwater leg ALONE is below (here: negative versus) its own buffer.

        This is the core account-level behavior that every other breakeven test misses
        (they're effectively single-position). A revert to PER-POSITION breakeven would
        leave ETH open (ETH-alone uPnL < ETH-alone buffer), so this test is a real
        discriminator for the netting.

        Two positions on the SAME account, both entering near t=0 (past the 1h breakeven
        window by the firing candle at t=120):
          - BTC qty 0.2 (entry 50000). At t=120 mark 51000 → uPnL = 0.2*(+1000) = +200.
          - ETH qty 3.164 (entry 3000; sized off post-BTC available ≈ 9494.5 → floor to
            qty_step). At t=120 mark 2990 → uPnL = 3.164*(-10) ≈ -31.64 (NEGATIVE, well
            below its own ~7.8 fee buffer).
        Combined uPnL ≈ +168.36 ≥ combined buffer ≈ 16.22 → the account-level rule fires
        and closes BOTH. max_duration is 5h (far away) so it can't interfere; the wide
        500% TP/SL are never touched by these small moves."""
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        config = _make_config(
            breakeven_timeout_hours=1.0,
            take_profit_pct=500.0, stop_loss_pct=500.0,
            max_trade_duration_hours=5.0, max_trades=5,
            leverage=20, capital_pct=5.0, fee_rate_pct=0.055, slippage_bps=0,
        )
        base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        # Two scans staggered like test_breakeven_excludes_max_duration_queued_position_
        # from_upnl_sum: BTC at t=0, ETH at t=30 (both past the 1h window by t=120).
        signals = [
            _make_signal(ticker="BTCUSDT", id=1, scan_id="s1", signal_time=base_time,
                         analysis_price=50000.0),
            _make_signal(ticker="ETHUSDT", id=2, score=7, scan_id="s2",
                         signal_time=base_time + timedelta(minutes=30), analysis_price=3000.0),
        ]
        # BTC: flat at 50000 until t=120 (combined uPnL stays below buffer so breakeven can't
        # fire early — its adverse-side low 49950 < entry), then a clean WINNER at t=120.
        # NOTE: BREAKEVEN_TIMEOUT marks on the ADVERSE side (a long uses the bar LOW), so the
        # winner candle's LOW (not close) must be the +winner: low 51000 → uPnL 0.2*(+1000)
        # = +200, well clear of the 500% TP.
        btc = [
            {"open_time": base_time + timedelta(minutes=5 * i),
             "open": 50000.0, "high": 50050.0, "low": 49950.0, "close": 50000.0, "volume": 100.0}
            for i in range(24)  # 0min .. 115min
        ]
        btc.append({"open_time": base_time + timedelta(minutes=120),
                    "open": 51000.0, "high": 51500.0, "low": 51000.0, "close": 51200.0, "volume": 100.0})
        # ETH: enters t=30, mildly underwater (2990) the whole time. Alone its uPnL
        # (≈ -31.64) is NEGATIVE — it can never clear its own ~7.8 fee buffer, so a
        # per-position breakeven would never fire for it. Needs a candle at t=120 so its
        # latest price is 2990 when the account-level rule evaluates.
        eth = [
            {"open_time": base_time + timedelta(minutes=30 + 5 * i),
             "open": 3000.0, "high": 2998.0, "low": 2985.0, "close": 2990.0, "volume": 100.0}
            for i in range(19)  # 30min .. 120min
        ]
        result = engine.run(config, signals, {"BTCUSDT": btc, "ETHUSDT": eth})
        by_symbol = {t["symbol"]: t for t in result.trades}
        assert set(by_symbol) == {"BTCUSDT", "ETHUSDT"}, by_symbol
        # BOTH legs close 'breakeven' on the same candle via account-level netting. ETH
        # only closes because BTC's +200 carries the COMBINED uPnL over the combined
        # buffer — ETH alone is underwater. If breakeven were per-position, ETH would
        # stay open and force-close 'backtest_end', failing this assertion.
        assert by_symbol["BTCUSDT"]["close_reason"] == "breakeven", by_symbol["BTCUSDT"]["close_reason"]
        assert by_symbol["ETHUSDT"]["close_reason"] == "breakeven", by_symbol["ETHUSDT"]["close_reason"]

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
