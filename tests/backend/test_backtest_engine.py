"""Tests for BacktestEngine — simulation engine skeleton and state management."""

import pytest
import threading
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass


class TestEngineCreation:
    """Test BacktestEngine instantiation and basic interface."""

    def test_engine_instantiates(self):
        from backend.services.backtest_engine import BacktestEngine
        engine = BacktestEngine()
        assert engine is not None

    def test_run_returns_simulation_result(self):
        from backend.services.backtest_engine import BacktestEngine
        from backend.schemas.backtest_schemas import SimulationResult

        engine = BacktestEngine()
        config = {
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
        }
        signals = []  # no signals → no trades
        klines = {}   # no klines needed for empty run

        result = engine.run(config, signals, klines)

        assert isinstance(result, SimulationResult)
        assert result.trades == []
        assert len(result.equity_curve) >= 0
        assert isinstance(result.metrics, dict)
        assert isinstance(result.warnings, list)
        assert isinstance(result.filter_stats, dict)

    def test_run_with_cancel_event_stops_early(self):
        from backend.services.backtest_engine import BacktestEngine, BacktestCancelled

        engine = BacktestEngine()
        cancel_event = threading.Event()
        cancel_event.set()  # Cancel immediately

        config = {"starting_capital": 10000.0, "leverage": 20, "capital_pct": 5.0,
                  "take_profit_pct": 150.0, "stop_loss_pct": 100.0, "direction": "straight",
                  "fee_rate_pct": 0.055, "slippage_bps": 2, "execution_mode": "batch",
                  "max_trades": 999, "skip_if_positions_open": False}

        # With signals that would normally be processed
        signals = [
            {"id": 1, "ticker": "BTCUSDT", "direction": "buy", "confidence": "high",
             "score": 8, "signal_time": datetime(2026, 1, 1, tzinfo=timezone.utc),
             "scan_id": "s1", "signal_source": "structured", "analysis_price": 50000.0}
        ]
        # Minimal klines (use timedelta to avoid minute overflow)
        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        klines = {"BTCUSDT": [
            {"open_time": base_time + timedelta(minutes=i * 5),
             "open": 50000.0, "high": 50100.0, "low": 49900.0, "close": 50050.0, "volume": 100.0}
            for i in range(200)
        ]}

        with pytest.raises(BacktestCancelled):
            engine.run(config, signals, klines, cancel_event=cancel_event)

    def test_on_progress_callback_called(self):
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        progress_values = []

        config = {"starting_capital": 10000.0, "leverage": 20, "capital_pct": 5.0,
                  "take_profit_pct": 150.0, "stop_loss_pct": 100.0, "direction": "straight",
                  "fee_rate_pct": 0.055, "slippage_bps": 2, "execution_mode": "batch",
                  "max_trades": 999, "skip_if_positions_open": False}

        result = engine.run(config, [], {}, on_progress=lambda pct: progress_values.append(pct))
        # Should call at least once (completion)
        assert len(progress_values) >= 1
        assert progress_values[-1] == 100  # final progress = 100%

    def test_diagnostics_surface_as_warnings(self, monkeypatch):
        """The engine must translate metrics['diagnostics'] counts into warnings.

        The engine builds closed_trades itself so bad data won't occur organically;
        inject a diagnostics payload by patching compute_all_metrics at its source
        module (the engine imports it lazily inside run()). A non-empty signal+kline
        is required so the run reaches the metrics-computation path (the empty-signals
        branch returns early before metrics are computed).
        """
        from backend.services import backtest_metrics
        from backend.services.backtest_engine import BacktestEngine

        monkeypatch.setattr(
            backtest_metrics, "compute_all_metrics",
            lambda trades, equity, config: {"diagnostics": {
                "trades_dropped_non_dict": 2,
                "equity_points_dropped_non_dict": 1,
                "trade_pnls_sanitized": 3,
                "equity_values_sanitized": 4,
            }},
        )
        config = {"starting_capital": 10000.0, "leverage": 20, "capital_pct": 5.0,
                  "take_profit_pct": 150.0, "stop_loss_pct": 100.0, "direction": "straight",
                  "fee_rate_pct": 0.055, "slippage_bps": 0, "execution_mode": "batch",
                  "max_trades": 999, "skip_if_positions_open": False}
        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        signals = [{"id": 1, "ticker": "BTCUSDT", "direction": "buy", "confidence": "high",
                    "score": 8, "signal_time": base, "scan_id": "s1",
                    "signal_source": "structured", "analysis_price": 50000.0}]
        klines = {"BTCUSDT": [
            {"open_time": base, "open": 50000.0, "high": 50100.0, "low": 49900.0, "close": 50000.0, "volume": 100.0},
            {"open_time": base + timedelta(minutes=5), "open": 50000.0, "high": 50100.0, "low": 49900.0, "close": 50000.0, "volume": 100.0},
        ]}
        result = BacktestEngine().run(config, signals, klines)
        assert "metrics_dropped_2_malformed_trades" in result.warnings
        assert "metrics_dropped_1_malformed_equity_points" in result.warnings
        assert "metrics_sanitized_3_non_finite_pnls" in result.warnings
        assert "metrics_sanitized_4_non_finite_equity_values" in result.warnings

    def test_clean_run_has_no_diagnostics_warnings(self, monkeypatch):
        """A clean metrics run (all-zero diagnostics) must NOT add any diagnostics warning."""
        from backend.services import backtest_metrics
        from backend.services.backtest_engine import BacktestEngine

        monkeypatch.setattr(
            backtest_metrics, "compute_all_metrics",
            lambda trades, equity, config: {"diagnostics": {
                "trades_dropped_non_dict": 0,
                "equity_points_dropped_non_dict": 0,
                "trade_pnls_sanitized": 0,
                "equity_values_sanitized": 0,
            }},
        )
        config = {"starting_capital": 10000.0, "leverage": 20, "capital_pct": 5.0,
                  "take_profit_pct": 150.0, "stop_loss_pct": 100.0, "direction": "straight",
                  "fee_rate_pct": 0.055, "slippage_bps": 0, "execution_mode": "batch",
                  "max_trades": 999, "skip_if_positions_open": False}
        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        signals = [{"id": 1, "ticker": "BTCUSDT", "direction": "buy", "confidence": "high",
                    "score": 8, "signal_time": base, "scan_id": "s1",
                    "signal_source": "structured", "analysis_price": 50000.0}]
        klines = {"BTCUSDT": [
            {"open_time": base, "open": 50000.0, "high": 50100.0, "low": 49900.0, "close": 50000.0, "volume": 100.0},
            {"open_time": base + timedelta(minutes=5), "open": 50000.0, "high": 50100.0, "low": 49900.0, "close": 50000.0, "volume": 100.0},
        ]}
        result = BacktestEngine().run(config, signals, klines)
        assert not any("metrics_dropped" in w or "metrics_sanitized" in w for w in result.warnings)


class TestSimulationState:
    """Test the internal state management."""

    def test_initial_state_has_starting_capital(self):
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        config = {"starting_capital": 5000.0, "leverage": 20, "capital_pct": 5.0,
                  "take_profit_pct": 150.0, "stop_loss_pct": 100.0, "direction": "straight",
                  "fee_rate_pct": 0.055, "slippage_bps": 2, "execution_mode": "batch",
                  "max_trades": 999, "skip_if_positions_open": False}

        result = engine.run(config, [], {})
        # Equity curve should show starting capital
        if result.equity_curve:
            assert result.equity_curve[0]["equity"] == 5000.0

    def test_zero_signals_produces_flat_equity(self):
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        config = {"starting_capital": 10000.0, "leverage": 20, "capital_pct": 5.0,
                  "take_profit_pct": 150.0, "stop_loss_pct": 100.0, "direction": "straight",
                  "fee_rate_pct": 0.055, "slippage_bps": 2, "execution_mode": "batch",
                  "max_trades": 999, "skip_if_positions_open": False}

        result = engine.run(config, [], {})
        assert result.trades == []
        assert "no_signals_found" in result.warnings or len(result.warnings) == 0


def _laconfig(**overrides):
    base = {
        "starting_capital": 10000.0, "leverage": 10, "capital_pct": 20.0,
        "take_profit_pct": 50.0, "stop_loss_pct": 900.0, "direction": "straight",
        "fee_rate_pct": 0.0, "slippage_bps": 0, "execution_mode": "batch",
        "max_trades": 1, "skip_if_positions_open": False, "min_score": 0.0,
        "confidence_filter": "any", "signal_sides": "both", "max_same_direction": None,
        "max_same_sector": None, "symbol_blacklist": None, "symbol_whitelist": None,
        "max_signal_age_minutes": None, "max_price_drift_pct": None,
        "adaptive_blacklist_enabled": False, "fill_to_max_trades": False,
        "target_goal_type": None, "target_goal_value": None, "simulation_interval": "5m",
        "max_drawdown_pct": 100.0, "smart_drawdown_close": False,
        "breakeven_timeout_hours": None, "max_trade_duration_hours": None,
        "trailing_profit_pct": None, "close_on_profit_pct": None,
    }
    base.update(overrides)
    return base


class TestEntryNoLookAhead:
    """Entry must NOT use look-ahead: a position fills at the next tradeable bar's
    OPEN (the first price available after the decision instant), and that same bar's
    high/low — which occur AFTER the open — are then legitimately evaluated for TP/SL.

    The prior bug filled at the entry bar's CLOSE (the end-of-bar price, ~one full
    candle into the future) while ALSO evaluating that bar's high/low (price action
    that PRECEDED the close-fill), fabricating exits from pre-entry price moves.
    """

    def test_long_into_falling_entry_bar_is_a_loss_not_a_fabricated_tp(self):
        """A long whose entry bar is RED (open 100, high 100, low 95, close 95) and
        whose price then stays at 95 must book a LOSS. The bug filled at close=95 and
        fired TP=99.75 on the bar's pre-entry high of 100 — a fabricated +win on a
        trade that lost money in reality."""
        from backend.services.backtest_engine import BacktestEngine
        # signal at 12:03:47 (UNALIGNED) → entry bar is the 12:05 candle
        sig_t = datetime(2026, 1, 1, 12, 3, 47, tzinfo=timezone.utc)
        signals = [{"id": 1, "ticker": "BTCUSDT", "direction": "buy", "confidence": "high",
                    "score": 8, "signal_time": sig_t, "scan_id": "s1",
                    "signal_source": "structured", "analysis_price": 100.0}]
        base = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        candles = []
        for i in range(30):
            t = base + timedelta(minutes=i * 5)
            if i == 0:      # 12:00 (pre-signal) flat 100
                candles.append({"open_time": t, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 100.0})
            elif i == 1:    # 12:05 ENTRY bar — RED: open 100, high 100, low 95, close 95
                candles.append({"open_time": t, "open": 100.0, "high": 100.0, "low": 95.0, "close": 95.0, "volume": 100.0})
            else:           # flat at 95 afterward → no TP ever (TP would be 100*1.05=105)
                candles.append({"open_time": t, "open": 95.0, "high": 95.0, "low": 95.0, "close": 95.0, "volume": 100.0})
        result = BacktestEngine().run(_laconfig(), signals, {"BTCUSDT": candles})
        assert len(result.trades) == 1
        trade = result.trades[0]
        # Entry fills at the entry bar's OPEN (100), not its close (95).
        assert trade["entry_price"] == pytest.approx(100.0)
        # Price never rose above 100, TP target is 105 → this CANNOT be a TP.
        assert trade["close_reason"] != "tp", "TP fabricated from pre-entry price action"
        # It is a real loss (force-closed at 95 at end of data).
        assert trade["pnl"] < 0

    def test_no_exit_on_the_entry_bar_itself(self):
        """A position must never close on the very bar it entered on using that bar's
        own high/low — those extremes are not all post-entry relative to a close-fill.
        With next-bar-open fill, an exit on the entry bar is only legitimate if driven
        by post-open action; here the entry bar is flat so no same-bar exit can occur."""
        from backend.services.backtest_engine import BacktestEngine
        sig_t = datetime(2026, 1, 1, 12, 3, 47, tzinfo=timezone.utc)
        signals = [{"id": 1, "ticker": "BTCUSDT", "direction": "buy", "confidence": "high",
                    "score": 8, "signal_time": sig_t, "scan_id": "s1",
                    "signal_source": "structured", "analysis_price": 100.0}]
        base = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        candles = []
        for i in range(20):
            t = base + timedelta(minutes=i * 5)
            # entry bar (12:05) is flat 100; a later bar spikes to TP
            if i == 5:
                candles.append({"open_time": t, "open": 100.0, "high": 106.0, "low": 100.0, "close": 106.0, "volume": 100.0})
            else:
                candles.append({"open_time": t, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 100.0})
        result = BacktestEngine().run(_laconfig(), signals, {"BTCUSDT": candles})
        assert len(result.trades) == 1
        trade = result.trades[0]
        assert trade["entry_price"] == pytest.approx(100.0)
        # TP (105) is hit on the 12:25 bar, NOT the 12:05 entry bar.
        assert trade["close_reason"] == "tp"
        assert trade["exit_time"] == base + timedelta(minutes=5 * 5)


class TestIntrabarEquityDrawdown:
    """EQUITY_DROP must react to an intra-candle drawdown breach, mirroring live.

    Production's close-rule evaluator runs on WS wallet ticks with zero debounce
    (close_rule_evaluator.py: drawdown split, immediate eval) — Bybit's live
    `totalEquity` reflects the real-time mark, so a transient intra-minute breach
    of the drawdown threshold FIRES. A candle-based backtest that only checks the
    bar CLOSE misses a breach that happened on the bar's high/low and then
    recovered by close — under-closing and holding positions production would have
    flattened. The engine must therefore evaluate equity drawdown on the bar's
    adverse extreme (high for shorts, low for longs), not just its close.
    """

    def _short_signal(self):
        sig_t = datetime(2026, 1, 1, 12, 3, 47, tzinfo=timezone.utc)
        return [{"id": 1, "ticker": "BTCUSDT", "direction": "sell", "confidence": "high",
                 "score": 8, "signal_time": sig_t, "scan_id": "s1",
                 "signal_source": "structured", "analysis_price": 100.0}]

    def _cfg(self):
        # capital_pct 100 + leverage 10: a +5% adverse move on a short is a
        # 50% equity drawdown. stop_loss_pct huge so SL never pre-empts the
        # equity rule; TP huge so no TP. fee/slippage 0 for exact arithmetic.
        return _laconfig(
            capital_pct=100.0, leverage=10, take_profit_pct=900.0,
            stop_loss_pct=900.0, max_drawdown_pct=50.0, smart_drawdown_close=False,
        )

    def test_intrabar_breach_on_high_fires_equity_drop(self):
        """Entry short @100. A later bar spikes to high=105 (a +5% adverse move =
        50% drawdown at 10x/100%) then CLOSES back at 100. The breach happened
        intrabar; close hides it. The engine MUST fire equity_drop on that bar."""
        from backend.services.backtest_engine import BacktestEngine
        base = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        candles = []
        for i in range(20):
            t = base + timedelta(minutes=i * 5)
            if i == 1:      # 12:05 entry bar — flat 100 (fills at open 100)
                candles.append({"open_time": t, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 100.0})
            elif i == 5:    # 12:25 — spikes to 105 intrabar, recovers to 100 at close
                candles.append({"open_time": t, "open": 100.0, "high": 105.0, "low": 100.0, "close": 100.0, "volume": 100.0})
            else:
                candles.append({"open_time": t, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 100.0})
        result = BacktestEngine().run(self._cfg(), self._short_signal(), {"BTCUSDT": candles})
        assert len(result.trades) == 1
        trade = result.trades[0]
        assert trade["close_reason"] == "equity_drop", (
            f"expected intrabar equity_drop, got {trade['close_reason']!r} "
            "(engine only checked the bar close and missed the high=105 breach)"
        )
        # Fired on the 12:25 bar, not later.
        assert trade["exit_time"] == base + timedelta(minutes=5 * 5)

    def test_no_breach_when_high_stays_under_threshold(self):
        """Control: same setup but the spike only reaches high=104 (40% drawdown,
        under the 50% threshold). The engine must NOT fire equity_drop — guards
        against an over-firing fix that closes on any adverse wick."""
        from backend.services.backtest_engine import BacktestEngine
        base = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        candles = []
        for i in range(8):
            t = base + timedelta(minutes=i * 5)
            if i == 5:      # high 104 = 40% drawdown < 50% threshold
                candles.append({"open_time": t, "open": 100.0, "high": 104.0, "low": 100.0, "close": 100.0, "volume": 100.0})
            else:
                candles.append({"open_time": t, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 100.0})
        result = BacktestEngine().run(self._cfg(), self._short_signal(), {"BTCUSDT": candles})
        assert len(result.trades) == 1
        assert result.trades[0]["close_reason"] != "equity_drop", (
            "fired equity_drop on a 40% wick — over-firing below the 50% threshold"
        )


def _fine_key(bar_open_dt):
    """Epoch key the engine uses to index a 1m window by its 5m bar open."""
    return int(bar_open_dt.timestamp())


class TestDrilldownEntry:
    """1-minute ENTRY drill-down: when a 1m window is injected for the entry bar, the
    fill should use the 1m open at/after the signal time (closer to production's
    actual fill instant) instead of the coarse 5m bar open — AND the entry bar's
    pre-fill minutes must not fabricate an exit (look-ahead guard). With NO fine data
    the engine must be byte-identical to today.
    """

    BASE = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    def _cfg(self, **ov):
        base = dict(capital_pct=20.0, leverage=10, take_profit_pct=900.0,
                    stop_loss_pct=900.0, fee_rate_pct=0.0, slippage_bps=0)
        base.update(ov)
        return _laconfig(**base)

    def _signal(self):
        # signal at 12:03:47 (unaligned) → entry bar is the 12:05 5m candle
        return [{"id": 1, "ticker": "BTCUSDT", "direction": "buy", "confidence": "high",
                 "score": 8, "signal_time": self.BASE + timedelta(minutes=3, seconds=47),
                 "scan_id": "s1", "signal_source": "structured", "analysis_price": 100.0}]

    def _klines(self):
        # 12:00 pre-signal flat 100; 12:05 entry bar OPENS at 100 but the 5m close is
        # 110; later bars flat 110 so no TP (tp huge anyway).
        out = []
        for i in range(20):
            t = self.BASE + timedelta(minutes=i * 5)
            if i == 1:   # 12:05 entry bar
                out.append({"open_time": t, "open": 100.0, "high": 112.0, "low": 100.0, "close": 110.0, "volume": 100.0})
            elif i == 0:
                out.append({"open_time": t, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 100.0})
            else:
                out.append({"open_time": t, "open": 110.0, "high": 110.0, "low": 110.0, "close": 110.0, "volume": 100.0})
        return {"BTCUSDT": out}

    def test_entry_fills_at_one_minute_open_not_five_minute_open(self):
        from backend.services.backtest_engine import BacktestEngine
        klines = self._klines()
        entry_bar = self.BASE + timedelta(minutes=5)  # 12:05 bar open
        # 1m candles for the 12:05 bar: 12:05,06,07,08,09. Signal is 12:03:47 → first
        # 1m at/after it within THIS bar is 12:05 (open 103) — but we set the minute
        # the engine should pick (12:05) to open at 103, distinct from the 5m open 100.
        fine = {"BTCUSDT": {_fine_key(entry_bar): [
            {"open_time": entry_bar + timedelta(minutes=m),
             "open": 103.0 if m == 0 else 105.0,
             "high": 105.0, "low": 103.0, "close": 105.0, "volume": 10.0}
            for m in range(5)
        ]}}
        result = BacktestEngine().run(self._cfg(), self._signal(), klines, fine_klines=fine)
        assert len(result.trades) == 1
        # Entry fills at the 1m open (103), NOT the 5m bar open (100).
        assert result.trades[0]["entry_price"] == pytest.approx(103.0), (
            f"entry should drill to the 1m open 103, got {result.trades[0]['entry_price']}"
        )

    def test_no_fine_klines_is_byte_identical(self):
        """A run with fine_klines=None must equal a run that never passes the param —
        proves the drill-down code is fully inert without injected 1m data."""
        from backend.services.backtest_engine import BacktestEngine
        klines = self._klines()
        a = BacktestEngine().run(self._cfg(), self._signal(), klines)
        b = BacktestEngine().run(self._cfg(), self._signal(), klines, fine_klines=None)
        c = BacktestEngine().run(self._cfg(), self._signal(), klines, fine_klines={})
        assert a.trades == b.trades == c.trades
        assert a.metrics.get("net_profit") == b.metrics.get("net_profit") == c.metrics.get("net_profit")

    def test_entry_bar_pre_fill_spike_does_not_fire_exit(self):
        """The entry 5m bar has a low of 50 (a huge pre-fill drop), but the 1m fill is
        at 12:05 and the post-entry 1m candles never reach the SL. A close-only or
        5m-high/low eval would fire SL from the pre-entry low; drill-down must not."""
        from backend.services.backtest_engine import BacktestEngine
        klines = self._klines()
        # make the 12:05 5m bar dip to 50 intrabar (pre-fill), recover to 110 close
        klines["BTCUSDT"][1] = {"open_time": self.BASE + timedelta(minutes=5),
                                "open": 100.0, "high": 112.0, "low": 50.0, "close": 110.0, "volume": 100.0}
        entry_bar = self.BASE + timedelta(minutes=5)
        # post-entry 1m candles stay 103-110 (never near a stop)
        fine = {"BTCUSDT": {_fine_key(entry_bar): [
            {"open_time": entry_bar + timedelta(minutes=m), "open": 103.0,
             "high": 110.0, "low": 103.0, "close": 110.0, "volume": 10.0}
            for m in range(5)
        ]}}
        cfg = self._cfg(stop_loss_pct=50.0)  # SL ~95 for a long at 103/10x → 50 would hit it
        result = BacktestEngine().run(cfg, self._signal(), klines, fine_klines=fine)
        assert len(result.trades) == 1
        assert result.trades[0]["close_reason"] != "sl", (
            "fabricated an SL exit from the entry bar's PRE-fill low of 50 (look-ahead)"
        )


class TestDrilldownExit:
    """1-minute EXIT drill-down: when a 5m exit bar straddles BOTH TP and SL, the 5m
    engine resolves pessimistically (SL wins). With a 1m window the engine must take
    the level actually touched FIRST. Without fine data → unchanged pessimistic SL.
    """

    BASE = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    def _cfg(self):
        # long, 10x, TP +5% (→105), SL -5% (→95). entry at 100 (5m open, no entry drill).
        return _laconfig(
            capital_pct=20.0, leverage=10, take_profit_pct=50.0, stop_loss_pct=50.0,
            fee_rate_pct=0.0, slippage_bps=0,
        )

    def _signal(self):
        # aligned signal → entry bar is 12:05, fills at its open (100). No entry drill.
        return [{"id": 1, "ticker": "BTCUSDT", "direction": "buy", "confidence": "high",
                 "score": 8, "signal_time": self.BASE + timedelta(minutes=3, seconds=47),
                 "scan_id": "s1", "signal_source": "structured", "analysis_price": 100.0}]

    def _klines(self, straddle_bar_idx=3):
        """Flat 100 except the straddle bar, whose 5m high≥105 (TP) AND low≤95 (SL)."""
        out = []
        for i in range(12):
            t = self.BASE + timedelta(minutes=i * 5)
            if i == 1:   # entry bar opens at 100
                out.append({"open_time": t, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 100.0})
            elif i == straddle_bar_idx:
                out.append({"open_time": t, "open": 100.0, "high": 106.0, "low": 94.0, "close": 100.0, "volume": 100.0})
            else:
                out.append({"open_time": t, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 100.0})
        return {"BTCUSDT": out}, self.BASE + timedelta(minutes=straddle_bar_idx * 5)

    def _exit_window(self, bar_open, order):
        """1m candles for the straddle bar. order='sl_first' touches 94 (SL) at min 0
        then 106 (TP) at min 3; 'tp_first' reverses."""
        seq = []
        for m in range(5):
            t = bar_open + timedelta(minutes=m)
            if order == "sl_first":
                lo, hi = (94.0, 100.0) if m == 0 else (100.0, 106.0) if m == 3 else (100.0, 100.0)
            else:  # tp_first
                lo, hi = (100.0, 106.0) if m == 0 else (94.0, 100.0) if m == 3 else (100.0, 100.0)
            seq.append({"open_time": t, "open": 100.0, "high": hi, "low": lo, "close": 100.0, "volume": 10.0})
        return {"BTCUSDT": {int(bar_open.timestamp()): seq}}

    def test_sl_touched_first_picks_sl(self):
        from backend.services.backtest_engine import BacktestEngine
        klines, bar = self._klines()
        fine = self._exit_window(bar, "sl_first")
        r = BacktestEngine().run(self._cfg(), self._signal(), klines, fine_klines=fine)
        assert r.trades[0]["close_reason"] == "sl"

    def test_tp_touched_first_picks_tp(self):
        from backend.services.backtest_engine import BacktestEngine
        klines, bar = self._klines()
        fine = self._exit_window(bar, "tp_first")
        r = BacktestEngine().run(self._cfg(), self._signal(), klines, fine_klines=fine)
        assert r.trades[0]["close_reason"] == "tp", (
            "TP was touched first in the 1m sequence but drill-down picked SL"
        )

    def test_no_fine_data_keeps_pessimistic_sl(self):
        from backend.services.backtest_engine import BacktestEngine
        klines, _ = self._klines()
        r = BacktestEngine().run(self._cfg(), self._signal(), klines)  # no fine
        assert r.trades[0]["close_reason"] == "sl", (
            "without 1m data, a TP&SL-straddle bar must keep the pessimistic SL default"
        )

    def test_single_1m_candle_double_touch_stays_pessimistic(self):
        """If the FIRST 1m candle itself straddles both TP and SL, order is still
        unknowable below 1m → keep pessimistic SL (long)."""
        from backend.services.backtest_engine import BacktestEngine
        klines, bar = self._klines()
        seq = [{"open_time": bar, "open": 100.0, "high": 106.0, "low": 94.0, "close": 100.0, "volume": 10.0}]
        seq += [{"open_time": bar + timedelta(minutes=m), "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 10.0} for m in range(1, 5)]
        fine = {"BTCUSDT": {int(bar.timestamp()): seq}}
        r = BacktestEngine().run(self._cfg(), self._signal(), klines, fine_klines=fine)
        assert r.trades[0]["close_reason"] == "sl"


