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
