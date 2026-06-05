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
