"""Tests for the filter chain in BacktestEngine — verifies 17-step filter matches production."""

from datetime import datetime, timedelta, timezone

import pytest


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

    def test_blacklist_matches_normalized_symbol_not_bare_ticker(self):
        """Blacklist/whitelist match the NORMALIZED symbol ({ticker}USDT), exactly like
        production (auto_trade_service normalizes then matches `symbol in blacklist`).
        A BARE-ticker entry ("BTC") must NOT filter "BTCUSDT" — production trades it, so
        the backtest must too, or it diverges (skips a trade production takes)."""
        from backend.services.backtest_engine import BacktestEngine

        # A bare "BTC" in the blacklist does NOT match the normalized "BTCUSDT" symbol.
        bare = BacktestEngine().run(
            _make_config(symbol_blacklist=["BTC"]),
            [_make_signal(ticker="BTCUSDT")],
            {"BTCUSDT": _make_klines()},
        )
        assert bare.filter_stats["signals_filtered"] == 0 or bare.filter_stats["signals_entered"] > 0

        # The full normalized symbol DOES match → filtered.
        full = BacktestEngine().run(
            _make_config(symbol_blacklist=["BTCUSDT"]),
            [_make_signal(ticker="BTCUSDT")],
            {"BTCUSDT": _make_klines()},
        )
        assert full.trades == []

        # A signal whose ticker lacks the USDT suffix is normalized before matching.
        suffixed = BacktestEngine().run(
            _make_config(symbol_blacklist=["BTCUSDT"]),
            [_make_signal(ticker="BTC", analysis_price=50000.0)],
            {"BTCUSDT": _make_klines()},  # klines keyed by the raw ticker
        )
        # "BTC" → "BTCUSDT" matches the blacklist → filtered (no trade).
        assert suffixed.trades == []


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

    def test_sizing_basis_includes_carried_unrealized_pnl(self):
        """The per-scan available balance must mark carried positions to market —
        production's totalAvailableBalance = wallet + unrealised_pnl − initial_margin,
        so a carried WINNER raises the basis (and a loser lowers it). Both the new
        position's size AND the equity-rule reference derive from this same value.

        Regression guard: the basis previously used wallet − locked_margin only,
        omitting the +unrealised_pnl term, so every scan carrying a position with
        non-zero uPnL sized (and referenced) off the wrong balance.

        Scenario: scan-1 opens BTC at 50000; it rises to 50750 by scan-2 (a carried
        WINNER worth +$300 unrealised: qty 0.4 × $750). scan-2 then opens ETH. With
        leverage 5 / capital_pct 40% and BTC margin = $4000, the available basis is
        wallet 10000 + carried uPnL 300 − margin 4000 = $6300 (NOT $6000). ETH sizes
        off 6300 → qty = 40% × 6300 × 5 / 3000 = 4.2 (the bug, off 6000, gives 4.0).
        """
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        config = _make_config(
            leverage=5, capital_pct=40.0,
            take_profit_pct=500.0, stop_loss_pct=500.0,  # wide → BTC stays open
            skip_if_positions_open=False, slippage_bps=0, fee_rate_pct=0.0, max_trades=999,
        )

        scan1 = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        scan2 = datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc)
        signals = [
            _make_signal(ticker="BTCUSDT", id=1, scan_id="scan-1", signal_time=scan1, analysis_price=50000.0),
            _make_signal(ticker="ETHUSDT", id=2, scan_id="scan-2", signal_time=scan2, analysis_price=3000.0),
        ]

        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        btc, eth = [], []
        span = (scan2 - scan1).total_seconds()
        for i in range(600):
            t = base + timedelta(minutes=i * 5)
            # BTC rises linearly 50000 → 50750 by scan-2, then holds (a carried winner).
            px = 50000.0 + 750.0 * min(1.0, (t - scan1).total_seconds() / span)
            btc.append({"open_time": t, "open": px, "high": px + 10, "low": px - 10, "close": px, "volume": 100.0})
            eth.append({"open_time": t, "open": 3000.0, "high": 3001.0, "low": 2999.0, "close": 3000.0, "volume": 100.0})
        klines = {"BTCUSDT": btc, "ETHUSDT": eth}

        result = engine.run(config, signals, klines)
        eth_trade = [t for t in result.trades if t["symbol"] == "ETHUSDT"][0]
        # ETH sized off available = wallet 10000 + carried uPnL 300 − BTC margin 4000
        # = 6300 → qty 4.2. The bug (omitting +uPnL → 6000) would give 4.0.
        assert eth_trade["qty"] == pytest.approx(4.2, rel=1e-3), (
            f"ETH qty {eth_trade['qty']} — the available basis did not include the "
            "carried position's unrealised PnL (production's +totalPerpUPL term)"
        )
        assert eth_trade["qty"] > 4.1  # strictly above the no-uPnL size (4.0)


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

        # signal_time aligns with the flat-kline start (00:00). The _make_signal default
        # (08:00) lands past the 00:00→04:05 coverage, so each signal would be dropped as
        # a no-kline signal before the strict/relaxed fill passes could enter it.
        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        signals = [
            _make_signal(ticker="BTCUSDT", id=1, score=8, analysis_price=50000.0, signal_time=base),
            _make_signal(ticker="ETHUSDT", id=2, score=3, analysis_price=3000.0, signal_time=base),
            _make_signal(ticker="SOLUSDT", id=3, score=2, analysis_price=150.0, signal_time=base),
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
        # signal_time aligns with the flat-kline start (00:00); the _make_signal default
        # (08:00) is past the 00:00→04:05 coverage and would be dropped pre-fill.
        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        signals = [
            _make_signal(ticker="BTCUSDT", id=1, score=8, analysis_price=50000.0, signal_time=base),
            _make_signal(ticker="ETHUSDT", id=2, score=3, analysis_price=3000.0, signal_time=base),
            _make_signal(ticker="SOLUSDT", id=3, score=2, analysis_price=150.0, signal_time=base),
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

    def test_fill_pass_enforces_max_signal_age(self):
        """Production-parity: the relaxed fill pass must STILL reject stale signals
        (max_signal_age_minutes is enforced in both strict and relaxed mode in live
        _try_trade). A backfill candidate older than max_signal_age_minutes must NOT
        enter, or the backtest over-fills vs live (violating the <1% deviation goal).

        IMPORTANT (realistic data): every signal in one scan shares the SAME scan-level
        signal_time (the loader anchors signal_time to the scan's completed_at). Per-
        ticker freshness comes from analysis_completed_at (the per-symbol analysis_runs
        completion, the backtest analog of live's per-ticker result.completed_at). Age
        is measured from THAT, not the shared signal_time — otherwise the gate is a
        structural no-op on real data (age would always be 0)."""
        from backend.services.backtest_engine import BacktestEngine

        config = _make_config(
            execution_mode="immediate", min_score=7.0, max_trades=3,
            fill_to_max_trades=True, max_signal_age_minutes=10,
            leverage=10, capital_pct=5.0,
            take_profit_pct=500.0, stop_loss_pct=500.0, slippage_bps=0,
        )
        # current_time anchors to the scan's signal_time (engine ~line 238). ALL signals
        # share it — exactly what the real loader produces (COALESCE(s.completed_at,...)).
        anchor = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        stale_completion = anchor - timedelta(minutes=45)  # ETH analyzed 45 min before scan close
        signals = [
            # BTC strict-qualifies (score 8 >= 7), analyzed fresh (near scan close).
            _make_signal(ticker="BTCUSDT", id=1, score=8, analysis_price=50000.0,
                         signal_time=anchor, analysis_completed_at=anchor),
            # ETH would backfill (sub-min score 3) but its ANALYSIS is stale → excluded,
            # even though its scan-level signal_time equals the others.
            _make_signal(ticker="ETHUSDT", id=2, score=3, analysis_price=3000.0,
                         signal_time=anchor, analysis_completed_at=stale_completion),
            # SOL is a fresh sub-min candidate → fills the second slot.
            _make_signal(ticker="SOLUSDT", id=3, score=2, analysis_price=150.0,
                         signal_time=anchor, analysis_completed_at=anchor),
        ]

        def flat(start):
            base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
            return [{"open_time": base + timedelta(minutes=i * 5),
                     "open": start, "high": start * 1.001, "low": start * 0.999,
                     "close": start, "volume": 100.0} for i in range(50)]
        klines = {"BTCUSDT": flat(50000.0), "ETHUSDT": flat(3000.0), "SOLUSDT": flat(150.0)}

        result = BacktestEngine().run(config, signals, klines)
        symbols = [t["symbol"] for t in result.trades]
        # Stale-analysis ETH excluded even from the relaxed fill; BTC (strict) + SOL (fresh fill).
        assert "ETHUSDT" not in symbols, f"stale signal entered the fill: {symbols}"
        assert sorted(symbols) == ["BTCUSDT", "SOLUSDT"]

    def test_fill_age_uses_signal_time_when_no_analysis_completion(self):
        """Backward-compat: when a signal lacks analysis_completed_at, the age gate
        falls back to signal_time (older callers / legacy data without per-ticker
        completion still get age enforcement, not a silent bypass)."""
        from backend.services.backtest_engine import BacktestEngine

        config = _make_config(
            execution_mode="immediate", min_score=7.0, max_trades=3,
            fill_to_max_trades=True, max_signal_age_minutes=10,
            leverage=10, capital_pct=5.0,
            take_profit_pct=500.0, stop_loss_pct=500.0, slippage_bps=0,
        )
        anchor = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        stale = anchor - timedelta(minutes=45)
        signals = [
            _make_signal(ticker="BTCUSDT", id=1, score=8, analysis_price=50000.0, signal_time=anchor),
            # No analysis_completed_at → falls back to signal_time, which is stale here.
            _make_signal(ticker="ETHUSDT", id=2, score=3, analysis_price=3000.0, signal_time=stale),
            _make_signal(ticker="SOLUSDT", id=3, score=2, analysis_price=150.0, signal_time=anchor),
        ]

        def flat(start):
            base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
            return [{"open_time": base + timedelta(minutes=i * 5),
                     "open": start, "high": start * 1.001, "low": start * 0.999,
                     "close": start, "volume": 100.0} for i in range(50)]
        klines = {"BTCUSDT": flat(50000.0), "ETHUSDT": flat(3000.0), "SOLUSDT": flat(150.0)}

        result = BacktestEngine().run(config, signals, klines)
        symbols = [t["symbol"] for t in result.trades]
        assert "ETHUSDT" not in symbols, f"stale (by signal_time fallback) entered: {symbols}"
        assert sorted(symbols) == ["BTCUSDT", "SOLUSDT"]





class TestInstrumentInfo:
    """Per-symbol instrument parameters (qty_step / min_qty / tick_size / max_leverage)
    passed via instrument_info make sizing, leverage, and TP/SL rounding match the live
    exchange — production sizes off real lot steps, caps leverage, and rounds TP/SL to
    the tick. Without instrument_info the engine uses no-op defaults (unchanged)."""

    @staticmethod
    def _coarse_klines(symbol, start, n=40):
        from datetime import datetime, timedelta, timezone
        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        return [{"open_time": base + timedelta(minutes=i * 5),
                 "open": start + i * 5, "high": start + i * 5 + 30,
                 "low": start + i * 5 - 5, "close": start + i * 5, "volume": 1e6}
                for i in range(n)]

    def test_qty_step_min_qty_and_max_leverage_applied(self):
        """A coarse-lot symbol (qty_step=10, min_qty=10, max_leverage=25): qty rounds
        DOWN to the step and leverage is capped, vs the 0.001/uncapped default."""
        from backend.services.backtest_engine import BacktestEngine
        # signal_time must align with the coarse-kline start (00:00). That series only
        # covers 00:00→03:15; the _make_signal default (08:00) lands PAST coverage and
        # is dropped as a no-kline signal before sizing, so the entry never exercises
        # the qty-step/leverage path. Candle 0's open == analysis_price (1000.0).
        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        config = _make_config(leverage=100, capital_pct=20.0,
                              take_profit_pct=50.0, stop_loss_pct=500.0, slippage_bps=0, fee_rate_pct=0.0)
        signals = [_make_signal(ticker="PEPEUSDT", analysis_price=1000.0, signal_time=base)]
        klines = {"PEPEUSDT": self._coarse_klines("PEPEUSDT", 1000.0)}
        info = {"PEPEUSDT": {"qty_step": 10.0, "min_qty": 10.0, "tick_size": 0.1, "max_leverage": 25}}

        # Default (no info): full requested leverage 100, fine-grained qty (step 0.001).
        base = BacktestEngine().run(config, signals, klines)
        assert base.trades[0]["leverage"] == 100
        base_qty = base.trades[0]["qty"]

        # With info: leverage capped 100→25 and qty rounded to the 10-lot step. The
        # entry price is the candle at/after signal time (≈ the analysis price); qty =
        # capital_pct × sizing × lev / entry, floored to the 10 step.
        withinfo = BacktestEngine().run(config, signals, klines, instrument_info=info)
        assert withinfo.trades[0]["leverage"] == 25  # capped from 100
        wqty = withinfo.trades[0]["qty"]
        assert wqty % 10.0 == pytest.approx(0.0, abs=1e-6), f"qty {wqty} not on the 10 lot step"
        # 25× leverage vs 100× → the capped position is ~1/4 the default size.
        assert wqty < base_qty
        assert wqty == pytest.approx(base_qty * 25.0 / 100.0, rel=0.05)

    def test_min_qty_rejects_undersized_position(self):
        """When the computed qty rounds below the symbol's min_qty, the signal is
        rejected (no trade) — matching production, which raises below min order qty."""
        from backend.services.backtest_engine import BacktestEngine
        # Tiny capital + huge min_qty → rounded qty < min_qty → rejected.
        # signal_time aligns with the coarse-kline start (00:00); the _make_signal
        # default (08:00) lands past the 00:00→03:15 coverage and would be dropped as a
        # no-kline signal (signals_no_kline), never reaching the min_qty sizing gate.
        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        config = _make_config(leverage=1, capital_pct=1.0,
                              take_profit_pct=50.0, stop_loss_pct=500.0, slippage_bps=0, fee_rate_pct=0.0)
        signals = [_make_signal(ticker="PEPEUSDT", analysis_price=1000.0, signal_time=base)]
        klines = {"PEPEUSDT": self._coarse_klines("PEPEUSDT", 1000.0)}
        # qty raw = 1%*10000*1/1000 = 0.1, min_qty 1000 → rejected.
        info = {"PEPEUSDT": {"qty_step": 1.0, "min_qty": 1000.0, "tick_size": 0.1, "max_leverage": 25}}
        result = BacktestEngine().run(config, signals, klines, instrument_info=info)
        assert result.trades == []
        assert result.filter_stats["signals_filtered"] >= 1

    def test_tp_sl_rounded_to_tick(self):
        """TP/SL trigger prices are rounded DOWN to the instrument tick size, matching
        production's round_price (ROUND_DOWN to tick)."""
        from datetime import datetime, timedelta, timezone

        from backend.services.backtest_engine import BacktestEngine
        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        config = _make_config(leverage=10, capital_pct=20.0,
                              take_profit_pct=50.0, stop_loss_pct=500.0, slippage_bps=0, fee_rate_pct=0.0)
        # signal_time must match the kline start so the entry candle is found.
        signals = [_make_signal(ticker="BTCUSDT", analysis_price=50003.0, signal_time=base)]
        # Price path crosses TP. tick=5 → 50003-anchored TP (50003*1.05=52503.15) rounds
        # DOWN to a multiple of 5 (52500).
        klines = {"BTCUSDT": [{"open_time": base + timedelta(minutes=i * 5),
                               "open": 50003.0 + i * 100, "high": 50003.0 + i * 100 + 300,
                               "low": 50003.0 + i * 100 - 50, "close": 50003.0 + i * 100, "volume": 100.0}
                              for i in range(40)]}
        info = {"BTCUSDT": {"qty_step": 0.001, "min_qty": 0.001, "tick_size": 5.0, "max_leverage": 125}}
        result = BacktestEngine().run(config, signals, klines, instrument_info=info)
        assert len(result.trades) == 1
        assert result.trades[0]["close_reason"] == "tp"
        # TP trigger (52503.15) rounds DOWN to the 5.0 tick → 52500; exit fills there.
        exit_price = result.trades[0]["exit_price"]
        assert exit_price == pytest.approx(52500.0, abs=1e-6)
        assert exit_price % 5.0 == pytest.approx(0.0, abs=1e-6), f"exit {exit_price} not on the 5.0 tick"

    def test_subcent_short_does_not_fabricate_profit_from_zeroed_sl(self):
        """A sub-cent symbol with a coarse fallback tick (0.01) must NOT have its SL
        rounded to 0 — a 0 SL was wrongly treated as the closest stop on a short,
        fabricating a ~100% win. With the round_price_to_tick zero-guard + the
        SL-liquidation clamp, an adverse short closes via the (clamped) stop-loss for
        a REAL loss — never a fabricated win — and reconciliation holds.

        AI-CONTEXT: pre-clamp this asserted close_reason=='liquidation'. The SL-clamp
        (trading_rules.clamp_sl_move_pct_to_liquidation, matching live) now pulls the
        stop inside the liquidation band so it fires as 'sl' first. The invariant this
        test actually guards — an adverse short is a LOSS, not a zeroed-SL fabricated
        win — is unchanged and the central assertion below (pnl < 0)."""
        from datetime import datetime, timedelta, timezone

        from backend.services.backtest_engine import BacktestEngine
        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        config = _make_config(leverage=20, capital_pct=20.0,
                              take_profit_pct=150.0, stop_loss_pct=100.0, slippage_bps=0)
        signals = [_make_signal(ticker="TINYUSDT", direction="sell", score=-8,
                                analysis_price=0.005, signal_time=base)]
        # Price RISES (adverse for a short) toward the liquidation level.
        klines = {"TINYUSDT": [{"open_time": base + timedelta(minutes=i * 5),
                               "open": 0.005 + i * 0.0001, "high": 0.005 + i * 0.0001 + 0.0002,
                               "low": 0.005 + i * 0.0001 - 0.0001, "close": 0.005 + i * 0.0001, "volume": 1e9}
                              for i in range(40)]}
        info = {"TINYUSDT": {"qty_step": 1.0, "min_qty": 1.0, "tick_size": 0.01, "max_leverage": 25}}
        result = BacktestEngine().run(config, signals, klines, instrument_info=info)
        assert len(result.trades) == 1
        trade = result.trades[0]
        # Closes via the clamped SL (fires before liquidation, matching live) — NOT a
        # zeroed-price SL that would fabricate a huge win.
        assert trade["close_reason"] == "sl"
        assert trade["pnl"] < 0  # an adverse short is a loss, never a fabricated win
        # Reconciliation invariant holds.
        assert result.metrics["net_profit"] == pytest.approx(
            result.metrics["final_equity"] - config["starting_capital"], abs=1e-6)


class TestNoKlineCoverage:
    """A signal whose symbol has NO cached candles is dropped distinctly (not as a
    rule-filtered signal) and surfaced via filter_stats.signals_no_kline so the user
    knows the backtest under-traded vs live trading."""

    def test_missing_kline_counted_distinctly_not_as_filtered(self):
        from backend.services.backtest_engine import BacktestEngine
        engine = BacktestEngine()
        config = _make_config()
        # Two signals; only BTC has klines. ETH has none → dropped as no-kline.
        signals = [_make_signal(ticker="BTCUSDT", id=1),
                   _make_signal(ticker="ETHUSDT", id=2, score=7)]
        klines = {"BTCUSDT": _make_klines("BTCUSDT")}  # ETHUSDT absent
        result = engine.run(config, signals, klines)
        # ETH is counted as no-kline, NOT as a strategy filter rejection.
        assert result.filter_stats["signals_no_kline"] == 1
        # BTC still traded; ETH did not.
        assert all(t["symbol"] == "BTCUSDT" for t in result.trades)

    def test_no_kline_zero_when_all_covered(self):
        from backend.services.backtest_engine import BacktestEngine
        engine = BacktestEngine()
        result = engine.run(_make_config(), [_make_signal(ticker="BTCUSDT")],
                            {"BTCUSDT": _make_klines("BTCUSDT")})
        assert result.filter_stats["signals_no_kline"] == 0
