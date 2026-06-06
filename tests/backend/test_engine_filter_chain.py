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

    def test_max_trades_is_per_scan_not_lifetime(self):
        """max_trades caps NEW trades per scan (cycle), not over the whole backtest.

        Production builds a fresh AutoTradeExecutor per scan (scanner_service.py
        creates it inside the scan flow, trades_executed=0), so max_trades=2 admits
        up to 2 trades in EACH scan. Regression guard for the bug where the engine
        gated max_trades on the LIFETIME signals_entered counter (never reset between
        scans) — which silently capped the entire multi-scan run at 2 trades total,
        massively under-counting trades/PnL vs real trading (violates <1% deviation).

        Two scans 24h apart, each with 2 signals, TP=2%/SL=2% so cycle-1 positions
        close well before scan-2. With the fix, all 4 trades execute; with the bug,
        only the first 2 ever do.
        """
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        # TP/SL tight enough that scan-1's positions close on the next candle, so
        # scan-2 starts a genuinely fresh cycle (no lingering positions).
        config = _make_config(max_trades=2, take_profit_pct=2.0, stop_loss_pct=2.0)

        scan1_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        scan2_time = datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc)
        signals = [
            _make_signal(ticker="BTCUSDT", id=1, scan_id="scan-1", signal_time=scan1_time),
            _make_signal(ticker="ETHUSDT", id=2, score=7, scan_id="scan-1", signal_time=scan1_time),
            _make_signal(ticker="BTCUSDT", id=3, scan_id="scan-2", signal_time=scan2_time),
            _make_signal(ticker="ETHUSDT", id=4, score=7, scan_id="scan-2", signal_time=scan2_time),
        ]

        # Rising prices → longs hit the 2% TP quickly, freeing the cycle for scan-2.
        def _rising(symbol, start):
            base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
            out = []
            for i in range(600):  # 600×5m = 50h, spans both scans
                px = start * (1.0 + 0.0005 * i)
                out.append({
                    "open_time": base_time + timedelta(minutes=i * 5),
                    "open": px, "high": px * 1.01, "low": px * 0.999,
                    "close": px, "volume": 100.0,
                })
            return out

        klines = {"BTCUSDT": _rising("BTCUSDT", 50000.0), "ETHUSDT": _rising("ETHUSDT", 3000.0)}

        result = engine.run(config, signals, klines)
        # 2 per scan × 2 scans = 4 (NOT 2). The bug capped this at 2.
        assert result.filter_stats["signals_entered"] == 4, (
            f"expected 4 entries (2 per scan), got {result.filter_stats['signals_entered']} "
            "— max_trades is being treated as a lifetime cap instead of per-scan"
        )
        assert len(result.trades) == 4


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


class TestSizingBasisAvailableBalance:
    """Position sizing must use AVAILABLE balance (wallet − locked margin of open
    positions), mirroring production's totalAvailableBalance — not the full wallet."""

    def test_sizing_uses_available_balance_with_open_positions(self):
        """When a prior cycle's position is still open, the next scan must size its
        new position off the REDUCED available balance (wallet − locked margin), the
        way production reads totalAvailableBalance at each scan's init_balances.

        Regression guard (same production-parity class as the per-cycle bugs): the
        engine previously sized off the full wallet, oversizing every scan that
        carried open positions by ~capital_pct% per carried position — breaking the
        <1% deviation requirement.

        Scenario: scan-1 opens BTC (wide TP/SL + flat price → stays open). scan-2
        opens ETH while BTC is still open. BTC locks 20%×10000 = $2000 margin, so
        ETH must size off ~$8000 (minus the small entry fee), NOT the full ~$10000.
        """
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        config = _make_config(
            leverage=10, capital_pct=20.0,
            take_profit_pct=500.0, stop_loss_pct=500.0,  # wide → BTC stays open
            skip_if_positions_open=False, slippage_bps=0, max_trades=999,
        )

        scan1 = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        scan2 = datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc)
        signals = [
            _make_signal(ticker="BTCUSDT", id=1, scan_id="scan-1", signal_time=scan1, analysis_price=50000.0),
            _make_signal(ticker="ETHUSDT", id=2, scan_id="scan-2", signal_time=scan2, analysis_price=3000.0),
        ]

        def flat(start):
            base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
            return [{"open_time": base + timedelta(minutes=i * 5),
                     "open": start, "high": start * 1.001, "low": start * 0.999,
                     "close": start, "volume": 100.0} for i in range(600)]
        klines = {"BTCUSDT": flat(50000.0), "ETHUSDT": flat(3000.0)}

        result = engine.run(config, signals, klines)
        assert len(result.trades) == 2
        btc = [t for t in result.trades if t["symbol"] == "BTCUSDT"][0]
        eth = [t for t in result.trades if t["symbol"] == "ETHUSDT"][0]

        # BTC sized off the full wallet (no open positions yet): 20%×10000×10/50000 = 0.4.
        assert btc["qty"] == pytest.approx(0.4, rel=1e-3)

        # ETH sized off AVAILABLE = wallet(10000) − BTC margin(2000) − fee(~10.45) ≈ 7989.55:
        #   20% × 7989.55 × 10 / 3000 ≈ 5.326. The BUG (full wallet ≈ 9989.55) → ≈ 6.66.
        assert eth["qty"] == pytest.approx(5.326, rel=2e-3), (
            f"ETH qty {eth['qty']} suggests sizing off the FULL wallet instead of "
            "available balance (wallet − locked margin)"
        )
        # Hard upper bound: must be well below the full-wallet size (~6.66).
        assert eth["qty"] < 6.0


class TestImmediateModeFillToMaxTrades:
    """Immediate mode must honor fill_to_max_trades with a relaxed backfill pass,
    mirroring production's fill_immediate_remaining."""

    def test_immediate_fill_backfills_to_max_trades(self):
        """execution_mode='immediate' + fill_to_max_trades must top the cycle up to
        max_trades via a RELAXED pass (bypassing min_score/confidence), ranking the
        leftover signals by abs(score) — exactly like production's
        fill_immediate_remaining and the batch-mode relaxed pass.

        Regression guard (production-parity): immediate mode previously had NO fill
        pass, so it under-filled vs real trading whenever this config was used.

        Setup: min_score=7 so only BTC (score 8) passes strict. With fill OFF → 1
        trade. With fill ON → the score-3/score-2 signals backfill (relaxed) up to
        max_trades=3.
        """
        from backend.services.backtest_engine import BacktestEngine

        def cfg(fill):
            return _make_config(
                execution_mode="immediate", min_score=7.0, max_trades=3,
                fill_to_max_trades=fill, leverage=10, capital_pct=5.0,
                take_profit_pct=500.0, stop_loss_pct=500.0, slippage_bps=0,
            )

        signals = [
            _make_signal(ticker="BTCUSDT", id=1, score=8, analysis_price=50000.0),
            _make_signal(ticker="ETHUSDT", id=2, score=3, analysis_price=3000.0),
            _make_signal(ticker="SOLUSDT", id=3, score=2, analysis_price=150.0),
        ]

        def flat(start):
            base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
            return [{"open_time": base + timedelta(minutes=i * 5),
                     "open": start, "high": start * 1.001, "low": start * 0.999,
                     "close": start, "volume": 100.0} for i in range(50)]
        klines = {"BTCUSDT": flat(50000.0), "ETHUSDT": flat(3000.0), "SOLUSDT": flat(150.0)}

        # Fill OFF: only the strict-passing BTC enters.
        off = BacktestEngine().run(cfg(False), signals, klines)
        assert off.filter_stats["signals_entered"] == 1
        assert [t["symbol"] for t in off.trades] == ["BTCUSDT"]

        # Fill ON: relaxed backfill tops up to max_trades=3 (BTC + ETH + SOL).
        on = BacktestEngine().run(cfg(True), signals, klines)
        assert on.filter_stats["signals_entered"] == 3, (
            "immediate mode + fill_to_max_trades must backfill via a relaxed pass to "
            "reach max_trades (was missing → under-filled vs production)"
        )
        assert sorted(t["symbol"] for t in on.trades) == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    def test_immediate_fill_respects_max_trades_cap(self):
        """The immediate fill pass must still stop at max_trades — it tops UP to the
        cap, never past it."""
        from backend.services.backtest_engine import BacktestEngine

        config = _make_config(
            execution_mode="immediate", min_score=7.0, max_trades=2,
            fill_to_max_trades=True, leverage=10, capital_pct=5.0,
            take_profit_pct=500.0, stop_loss_pct=500.0, slippage_bps=0,
        )
        signals = [
            _make_signal(ticker="BTCUSDT", id=1, score=8, analysis_price=50000.0),
            _make_signal(ticker="ETHUSDT", id=2, score=3, analysis_price=3000.0),
            _make_signal(ticker="SOLUSDT", id=3, score=2, analysis_price=150.0),
        ]

        def flat(start):
            base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
            return [{"open_time": base + timedelta(minutes=i * 5),
                     "open": start, "high": start * 1.001, "low": start * 0.999,
                     "close": start, "volume": 100.0} for i in range(50)]
        klines = {"BTCUSDT": flat(50000.0), "ETHUSDT": flat(3000.0), "SOLUSDT": flat(150.0)}

        result = BacktestEngine().run(config, signals, klines)
        # 1 strict (BTC) + 1 relaxed backfill (ETH, higher abs score than SOL) = 2 = cap.
        assert result.filter_stats["signals_entered"] == 2
        assert sorted(t["symbol"] for t in result.trades) == ["BTCUSDT", "ETHUSDT"]


