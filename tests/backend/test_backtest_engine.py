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


class TestBreakevenTimeoutMarking:
    def test_breakeven_timeout_does_not_fire_on_favorable_close_only(self):
        from backend.services.backtest_engine import BacktestEngine

        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        signals = [{
            "id": 1,
            "ticker": "SHORTUSDT",
            "direction": "sell",
            "confidence": "high",
            "score": 8,
            "signal_time": base,
            "scan_id": "s1",
            "signal_source": "structured",
            "analysis_price": 100.0,
        }]
        klines = {"SHORTUSDT": [
            {"open_time": base, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1.0},
            # The close is very profitable for a short, but the bar high says the
            # account-level mark could still be adverse. BREAKEVEN_TIMEOUT should
            # not mass-close from the favorable close alone.
            {"open_time": base + timedelta(minutes=5), "open": 100.0, "high": 102.0, "low": 95.0, "close": 95.0, "volume": 1.0},
        ]}

        result = BacktestEngine().run(
            _laconfig(
                take_profit_pct=900.0,
                stop_loss_pct=900.0,
                breakeven_timeout_hours=0.01,
            ),
            signals,
            klines,
        )

        assert len(result.trades) == 1
        assert result.trades[0]["close_reason"] == "backtest_end"

    def test_breakeven_timeout_fires_when_adverse_mark_confirms_profit(self):
        from backend.services.backtest_engine import BacktestEngine

        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        signals = [{
            "id": 1,
            "ticker": "SHORTUSDT",
            "direction": "sell",
            "confidence": "high",
            "score": 8,
            "signal_time": base,
            "scan_id": "s1",
            "signal_source": "structured",
            "analysis_price": 100.0,
        }]
        klines = {"SHORTUSDT": [
            {"open_time": base, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1.0},
            {"open_time": base + timedelta(minutes=5), "open": 100.0, "high": 94.0, "low": 92.0, "close": 93.0, "volume": 1.0},
        ]}

        result = BacktestEngine().run(
            _laconfig(
                take_profit_pct=900.0,
                stop_loss_pct=900.0,
                breakeven_timeout_hours=0.01,
            ),
            signals,
            klines,
        )

        assert len(result.trades) == 1
        assert result.trades[0]["close_reason"] == "breakeven"

    def test_schedule_profit_round_does_not_use_synthetic_breakeven_mark(self):
        from backend.services.backtest_engine import BacktestEngine

        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        signals = [{
            "id": 1,
            "ticker": "SHORTUSDT",
            "direction": "sell",
            "confidence": "high",
            "score": 8,
            "signal_time": base,
            "scan_id": "s1",
            "signal_source": "structured",
            "analysis_price": 100.0,
        }]
        klines = {"SHORTUSDT": [
            {"open_time": base, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1.0},
            {"open_time": base + timedelta(minutes=5), "open": 100.0, "high": 98.0, "low": 97.0, "close": 97.5, "volume": 1.0},
        ]}

        result = BacktestEngine().run(
            _laconfig(
                scan_source={"mode": "schedule", "schedule_id": "sched-1"},
                take_profit_pct=900.0,
                stop_loss_pct=900.0,
                breakeven_timeout_hours=0.01,
                target_goal_type="profit_pct",
                target_goal_value=50.0,
            ),
            signals,
            klines,
        )

        assert len(result.trades) == 1
        assert result.trades[0]["close_reason"] == "backtest_end"

    def test_breakeven_does_not_use_post_smart_survivor_book_same_window(self):
        from backend.services.backtest_engine import BacktestEngine

        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        signals = [
            {
                "id": 1,
                "ticker": "LOSERUSDT",
                "direction": "buy",
                "confidence": "high",
                "score": 9,
                "signal_time": base,
                "scan_id": "s1",
                "signal_source": "structured",
                "analysis_price": 100.0,
            },
            {
                "id": 2,
                "ticker": "WINNERUSDT",
                "direction": "buy",
                "confidence": "high",
                "score": 8,
                "signal_time": base,
                "scan_id": "s1",
                "signal_source": "structured",
                "analysis_price": 100.0,
            },
        ]
        klines = {
            "LOSERUSDT": [
                {"open_time": base, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1.0},
                {"open_time": base + timedelta(minutes=5), "open": 100.0, "high": 100.0, "low": 60.0, "close": 60.0, "volume": 1.0},
            ],
            "WINNERUSDT": [
                {"open_time": base, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1.0},
                {"open_time": base + timedelta(minutes=5), "open": 100.0, "high": 120.0, "low": 120.0, "close": 120.0, "volume": 1.0},
                {"open_time": base + timedelta(minutes=10), "open": 120.0, "high": 120.0, "low": 120.0, "close": 120.0, "volume": 1.0},
            ],
        }

        result = BacktestEngine().run(
            _laconfig(
                capital_pct=50.0,
                leverage=2,
                max_trades=2,
                take_profit_pct=900.0,
                stop_loss_pct=900.0,
                max_drawdown_pct=10.0,
                smart_drawdown_close=True,
                breakeven_timeout_hours=0.01,
            ),
            signals,
            klines,
        )

        reasons_by_symbol = {trade["symbol"]: trade["close_reason"] for trade in result.trades}
        assert reasons_by_symbol["LOSERUSDT"] == "equity_drop_smart"
        assert reasons_by_symbol["WINNERUSDT"] == "backtest_end"


class TestLiveSelectionTiming:
    def test_live_selection_pin_overrides_algorithmic_score_order(self):
        from backend.services.backtest_engine import BacktestEngine

        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        scan_completed = base + timedelta(minutes=30)
        signals = [
            {
                "id": 1,
                "ticker": "OLDUSDT",
                "direction": "buy",
                "confidence": "high",
                "score": 9,
                "signal_time": scan_completed,
                "scan_started_at": base,
                "completed_at": base + timedelta(minutes=10),
                "scan_id": "s1",
                "signal_source": "structured",
                "analysis_price": 100.0,
            },
            {
                "id": 2,
                "ticker": "NEWUSDT",
                "direction": "buy",
                "confidence": "high",
                "score": 7,
                "signal_time": scan_completed,
                "scan_started_at": base,
                "completed_at": base + timedelta(minutes=20),
                "scan_id": "s1",
                "signal_source": "structured",
                "analysis_price": 100.0,
            },
        ]
        candles = [
            {
                "open_time": base + timedelta(minutes=i * 5),
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 100.0,
            }
            for i in range(24)
        ]

        result = BacktestEngine().run(
            _laconfig(
                max_trades=1,
                _live_selection_by_scan={"s1": [{"symbol": "NEWUSDT", "side": "Buy"}]},
            ),
            signals,
            {
                "OLDUSDT": list(candles),
                "NEWUSDT": list(candles),
            },
        )

        assert [t["symbol"] for t in result.trades] == ["NEWUSDT"]

    def test_empty_live_selection_pin_skips_scan(self):
        from backend.services.backtest_engine import BacktestEngine

        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        signals = [{
            "id": 1,
            "ticker": "OLDUSDT",
            "direction": "buy",
            "confidence": "high",
            "score": 9,
            "signal_time": base + timedelta(minutes=30),
            "scan_started_at": base,
            "completed_at": base + timedelta(minutes=10),
            "scan_id": "s1",
            "signal_source": "structured",
            "analysis_price": 100.0,
        }]
        candles = [
            {
                "open_time": base + timedelta(minutes=i * 5),
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 100.0,
            }
            for i in range(24)
        ]

        result = BacktestEngine().run(
            _laconfig(_live_selection_by_scan={"s1": []}),
            signals,
            {"OLDUSDT": candles},
        )

        assert result.trades == []

    def test_account_selection_time_controls_signal_age_before_ranking_pick(self):
        """Live checks max_signal_age at the account's actual placement time.

        The older candidate has the higher score and would win at scan completion,
        but it is stale by the live account selection timestamp. The backtest must
        skip it and pick the next eligible signal.
        """
        from backend.services.backtest_engine import BacktestEngine

        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        scan_completed = base + timedelta(minutes=60)
        selection_time = base + timedelta(minutes=130)

        signals = [
            {
                "id": 1,
                "ticker": "OLDUSDT",
                "direction": "buy",
                "confidence": "high",
                "score": 9,
                "signal_time": scan_completed,
                "scan_started_at": base,
                "completed_at": base + timedelta(minutes=5),
                "scan_id": "s1",
                "signal_source": "structured",
                "analysis_price": 100.0,
            },
            {
                "id": 2,
                "ticker": "NEWUSDT",
                "direction": "buy",
                "confidence": "high",
                "score": 8,
                "signal_time": scan_completed,
                "scan_started_at": base,
                "completed_at": base + timedelta(minutes=20),
                "scan_id": "s1",
                "signal_source": "structured",
                "analysis_price": 100.0,
            },
        ]

        candles = []
        for i in range(48):
            t = base + timedelta(minutes=i * 5)
            candles.append({
                "open_time": t,
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 100.0,
            })

        result = BacktestEngine().run(
            _laconfig(
                max_signal_age_minutes=120,
                max_trades=1,
                _selection_time_by_scan={"s1": selection_time},
            ),
            signals,
            {
                "OLDUSDT": list(candles),
                "NEWUSDT": list(candles),
            },
        )

        assert [t["symbol"] for t in result.trades] == ["NEWUSDT"]

    def test_null_completed_at_uses_analysis_completed_at_for_signal_age(self):
        """Rows with NULL completed_at still use analysis completion for age."""
        from backend.services.backtest_engine import BacktestEngine

        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        scan_completed = base + timedelta(minutes=60)
        selection_time = base + timedelta(minutes=240)
        signals = [
            {
                "id": 1,
                "ticker": "STALEUSDT",
                "direction": "sell",
                "confidence": "high",
                "score": -9,
                "signal_time": scan_completed,
                "scan_started_at": base,
                "completed_at": None,
                "analysis_completed_at": base + timedelta(minutes=10),
                "scan_id": "s1",
                "signal_source": "structured",
                "analysis_price": 100.0,
            },
            {
                "id": 2,
                "ticker": "FRESHUSDT",
                "direction": "sell",
                "confidence": "high",
                "score": -8,
                "signal_time": scan_completed,
                "scan_started_at": base,
                "completed_at": None,
                "analysis_completed_at": base + timedelta(minutes=180),
                "scan_id": "s1",
                "signal_source": "structured",
                "analysis_price": 100.0,
            },
        ]
        candles = [
            {
                "open_time": base + timedelta(minutes=i * 5),
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 100.0,
            }
            for i in range(60)
        ]

        result = BacktestEngine().run(
            _laconfig(
                max_signal_age_minutes=120,
                max_trades=1,
                _selection_time_by_scan={"s1": selection_time},
            ),
            signals,
            {"STALEUSDT": list(candles), "FRESHUSDT": list(candles)},
        )

        assert [t["symbol"] for t in result.trades] == ["FRESHUSDT"]

    def test_batch_uses_analysis_completed_at_to_rank_null_completed_at_rows(self):
        """Normal batch reconstructs live result completed_at from analysis time."""
        from backend.services.backtest_engine import BacktestEngine

        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        scan_completed = base + timedelta(minutes=60)
        signals = [
            {
                "id": 1,
                "ticker": "OLDUSDT",
                "direction": "sell",
                "confidence": "high",
                "score": -8,
                "signal_time": scan_completed,
                "scan_started_at": base,
                "completed_at": None,
                "analysis_completed_at": base + timedelta(minutes=20),
                "scan_id": "s1",
                "signal_source": "structured",
                "analysis_price": 100.0,
            },
            {
                "id": 2,
                "ticker": "NEWUSDT",
                "direction": "sell",
                "confidence": "high",
                "score": -8,
                "signal_time": scan_completed,
                "scan_started_at": base,
                "completed_at": None,
                "analysis_completed_at": base + timedelta(minutes=50),
                "scan_id": "s1",
                "signal_source": "structured",
                "analysis_price": 100.0,
            },
        ]
        candles = [
            {
                "open_time": base + timedelta(minutes=i * 5),
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 100.0,
            }
            for i in range(40)
        ]

        result = BacktestEngine().run(
            _laconfig(max_trades=1),
            signals,
            {"OLDUSDT": list(candles), "NEWUSDT": list(candles)},
        )

        assert [t["symbol"] for t in result.trades] == ["NEWUSDT"]

    def test_price_drift_uses_decision_time_mark_not_future_entry_open(self):
        from backend.services.backtest_engine import BacktestEngine

        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        decision_time = base + timedelta(minutes=3)
        signals = [{
            "id": 1,
            "ticker": "DRIFTUSDT",
            "direction": "sell",
            "confidence": "high",
            "score": -8,
            "signal_time": decision_time,
            "scan_started_at": base,
            "scan_id": "s1",
            "signal_source": "structured",
            "analysis_price": 100.0,
        }]
        klines = {"DRIFTUSDT": [
            # The live mark at decision time has already moved 5% in the sell
            # direction, so live skips for price_drift even though the future entry
            # bar opens back near the analysis price.
            {"open_time": base, "open": 100.0, "high": 100.0, "low": 95.0, "close": 95.0, "volume": 100.0},
            {"open_time": base + timedelta(minutes=5), "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 100.0},
        ]}

        result = BacktestEngine().run(
            _laconfig(max_price_drift_pct=3.0),
            signals,
            klines,
        )

        assert result.trades == []

    def test_schedule_price_drift_uses_adverse_mark_near_bar_open(self):
        from backend.services.backtest_engine import BacktestEngine

        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        decision_time = base + timedelta(seconds=5)
        signals = [{
            "id": 1,
            "ticker": "DRIFTUSDT",
            "direction": "sell",
            "confidence": "high",
            "score": -8,
            "signal_time": decision_time,
            "scan_started_at": base,
            "scan_id": "s1",
            "signal_source": "structured",
            "analysis_price": 100.0,
        }]
        klines = {"DRIFTUSDT": [
            # The 5m close is safe (-1%) but this decision is only five seconds into
            # the bar, where the live mark can still be near the adverse side.
            {"open_time": base, "open": 100.0, "high": 100.0, "low": 95.0, "close": 99.0, "volume": 100.0},
            {"open_time": base + timedelta(minutes=5), "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 100.0},
        ]}
        cfg = _laconfig(max_price_drift_pct=3.0)
        cfg["scan_source"] = {"mode": "schedule", "schedule_id": "sched"}

        result = BacktestEngine().run(cfg, signals, klines)

        assert result.trades == []

    def test_schedule_price_drift_uses_close_after_early_bar_window(self):
        from backend.services.backtest_engine import BacktestEngine

        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        decision_time = base + timedelta(minutes=3)
        signals = [{
            "id": 1,
            "ticker": "DRIFTUSDT",
            "direction": "sell",
            "confidence": "high",
            "score": -8,
            "signal_time": decision_time,
            "scan_started_at": base,
            "scan_id": "s1",
            "signal_source": "structured",
            "analysis_price": 100.0,
        }]
        klines = {"DRIFTUSDT": [
            # Later in the bar, the close is the better account-free proxy for the
            # exchange mark. The adverse low alone would incorrectly reject this.
            {"open_time": base, "open": 100.0, "high": 100.0, "low": 95.0, "close": 99.0, "volume": 100.0},
            {"open_time": base + timedelta(minutes=5), "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 100.0},
        ]}
        cfg = _laconfig(max_price_drift_pct=3.0)
        cfg["scan_source"] = {"mode": "schedule", "schedule_id": "sched"}

        result = BacktestEngine().run(cfg, signals, klines)

        assert [t["symbol"] for t in result.trades] == ["DRIFTUSDT"]

    def test_fill_to_max_only_attempts_remaining_slot_count(self):
        from backend.services.backtest_engine import BacktestEngine

        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        decision_time = base + timedelta(minutes=3)
        signals = [
            {
                "id": 1,
                "ticker": "GOODUSDT",
                "direction": "sell",
                "confidence": "high",
                "score": -8,
                "signal_time": decision_time,
                "scan_id": "s1",
                "signal_source": "structured",
                "analysis_price": 100.0,
            },
            {
                "id": 2,
                "ticker": "DRIFTUSDT",
                "direction": "sell",
                "confidence": "low",
                "score": -6,
                "signal_time": decision_time,
                "scan_id": "s1",
                "signal_source": "structured",
                "analysis_price": 100.0,
            },
            {
                "id": 3,
                "ticker": "NOKLINEUSDT",
                "direction": "sell",
                "confidence": "low",
                "score": -6,
                "signal_time": decision_time,
                "scan_id": "s1",
                "signal_source": "structured",
                "analysis_price": 100.0,
            },
            {
                "id": 4,
                "ticker": "LATEPASSUSDT",
                "direction": "sell",
                "confidence": "low",
                "score": -6,
                "signal_time": decision_time,
                "scan_id": "s1",
                "signal_source": "structured",
                "analysis_price": 100.0,
            },
        ]
        flat = [
            {"open_time": base, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 100.0},
            {"open_time": base + timedelta(minutes=5), "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 100.0},
        ]
        drifted = [
            {"open_time": base, "open": 100.0, "high": 100.0, "low": 95.0, "close": 95.0, "volume": 100.0},
            {"open_time": base + timedelta(minutes=5), "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 100.0},
        ]

        result = BacktestEngine().run(
            _laconfig(
                max_trades=3,
                fill_to_max_trades=True,
                min_score=7.0,
                confidence_filter="high",
                max_price_drift_pct=3.0,
            ),
            signals,
            {
                "GOODUSDT": list(flat),
                "DRIFTUSDT": drifted,
                "LATEPASSUSDT": list(flat),
            },
        )

        assert [trade["symbol"] for trade in result.trades] == ["GOODUSDT"]

    def test_scan_started_with_positions_uses_post_scan_recheck_order_after_clear(self):
        """If a scan starts with positions open, live rescues it through
        post_scan_recheck when the book clears before completion. That path ranks
        tied candidates by abs(score) only, preserving completion/insertion order.
        """
        from backend.services.backtest_engine import BacktestEngine

        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        first_complete = base + timedelta(minutes=12)
        second_start = base + timedelta(minutes=20)
        second_complete = base + timedelta(minutes=50)

        signals = [
            {
                "id": 1,
                "ticker": "PREVUSDT",
                "direction": "buy",
                "confidence": "high",
                "score": 8,
                "signal_time": first_complete,
                "scan_started_at": base,
                "scan_id": "s1",
                "signal_source": "structured",
                "analysis_price": 100.0,
            },
            {
                "id": 3,
                "ticker": "NEWUSDT",
                "direction": "sell",
                "confidence": "high",
                "score": -8,
                "signal_time": second_complete,
                "scan_started_at": second_start,
                "completed_at": None,
                "analysis_completed_at": base + timedelta(minutes=49),
                "scan_id": "s2",
                "signal_source": "structured",
                "analysis_price": 50.0,
            },
            {
                "id": 2,
                "ticker": "OLDUSDT",
                "direction": "sell",
                "confidence": "high",
                "score": -8,
                "signal_time": second_complete,
                "scan_started_at": second_start,
                "completed_at": None,
                "analysis_completed_at": base + timedelta(minutes=25),
                "scan_id": "s2",
                "signal_source": "structured",
                "analysis_price": 50.0,
            },
        ]

        prev = []
        flat = []
        for i in range(20):
            t = base + timedelta(minutes=i * 5)
            prev_high = 102.0 if t == base + timedelta(minutes=35) else 100.5
            prev.append({
                "open_time": t,
                "open": 100.0,
                "high": prev_high,
                "low": 99.5,
                "close": 100.0,
                "volume": 100.0,
            })
            flat.append({
                "open_time": t,
                "open": 50.0,
                "high": 50.0,
                "low": 50.0,
                "close": 50.0,
                "volume": 100.0,
            })

        result = BacktestEngine().run(
            _laconfig(
                leverage=10,
                take_profit_pct=10.0,
                max_trades=1,
                skip_if_positions_open=True,
            ),
            signals,
            {
                "PREVUSDT": prev,
                "OLDUSDT": list(flat),
                "NEWUSDT": list(flat),
            },
        )

        rescued = [t for t in result.trades if t.get("scan_id") == "s2"]
        assert [t["symbol"] for t in rescued] == ["OLDUSDT"]

    def test_schedule_post_scan_recheck_time_controls_signal_age(self):
        """Specific Schedule must evaluate rescued scans at the estimated recheck
        clock, not scan completion. Otherwise near-stale high-score candidates enter
        even though live would have aged them out by the time post_scan_recheck ran.
        """
        from backend.services.backtest_engine import BacktestEngine

        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        first_complete = base + timedelta(minutes=5)
        second_start = base + timedelta(minutes=10)
        second_complete = base + timedelta(minutes=50)
        recheck_time = base + timedelta(minutes=65)

        signals = [
            {
                "id": 1,
                "ticker": "PREVUSDT",
                "direction": "buy",
                "confidence": "high",
                "score": 8,
                "signal_time": first_complete,
                "scan_started_at": base,
                "scan_id": "s1",
                "signal_source": "structured",
                "analysis_price": 100.0,
            },
            {
                "id": 2,
                "ticker": "OLDUSDT",
                "direction": "sell",
                "confidence": "high",
                "score": -9,
                "signal_time": second_complete,
                "scan_started_at": second_start,
                "completed_at": base + timedelta(minutes=4),
                "scan_id": "s2",
                "signal_source": "structured",
                "analysis_price": 50.0,
            },
            {
                "id": 3,
                "ticker": "NEWUSDT",
                "direction": "sell",
                "confidence": "high",
                "score": -8,
                "signal_time": second_complete,
                "scan_started_at": second_start,
                "completed_at": base + timedelta(minutes=20),
                "scan_id": "s2",
                "signal_source": "structured",
                "analysis_price": 50.0,
            },
        ]

        prev = []
        flat = []
        for i in range(24):
            t = base + timedelta(minutes=i * 5)
            prev.append({
                "open_time": t,
                "open": 100.0,
                "high": 102.0 if t == base + timedelta(minutes=30) else 100.5,
                "low": 99.5,
                "close": 100.0,
                "volume": 100.0,
            })
            flat.append({
                "open_time": t,
                "open": 50.0,
                "high": 50.0,
                "low": 50.0,
                "close": 50.0,
                "volume": 100.0,
            })

        result = BacktestEngine().run(
            _laconfig(
                leverage=10,
                take_profit_pct=10.0,
                max_trades=1,
                skip_if_positions_open=True,
                max_signal_age_minutes=60,
                _schedule_post_scan_recheck_time_by_scan={"s2": recheck_time.isoformat()},
            ),
            signals,
            {
                "PREVUSDT": prev,
                "OLDUSDT": list(flat),
                "NEWUSDT": list(flat),
            },
        )

        rescued = [t for t in result.trades if t.get("scan_id") == "s2"]
        assert [t["symbol"] for t in rescued] == ["NEWUSDT"]


class TestLiveCloseRuleClock:
    def _signal(self, scan_id, t, *, started_at=None):
        return {
            "id": scan_id,
            "ticker": "CARRYUSDT",
            "direction": "buy",
            "confidence": "high",
            "score": 8,
            "signal_time": t,
            "scan_started_at": started_at or t,
            "scan_id": scan_id,
            "signal_source": "structured",
            "analysis_price": 100.0,
        }

    def _flat_klines(self, base, bars=30):
        return [
            {
                "open_time": base + timedelta(minutes=5 * i),
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 100.0,
            }
            for i in range(bars)
        ]

    def test_non_skipped_scan_recreates_breakeven_clock_for_carried_book(self):
        """Live recreates close rules on a non-skipped scan, even if an old
        position is still open. The breakeven timer must restart at that scan's
        decision clock, not keep aging from the original position entry.
        """
        from backend.services.backtest_engine import BacktestEngine

        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        second = base + timedelta(minutes=30)
        signals = [
            self._signal("s1", base),
            self._signal("s2", second),
        ]

        result = BacktestEngine().run(
            _laconfig(
                take_profit_pct=900.0,
                stop_loss_pct=900.0,
                breakeven_timeout_hours=1.0,
                skip_if_positions_open=False,
            ),
            signals,
            {"CARRYUSDT": self._flat_klines(base)},
        )

        assert len(result.trades) == 1
        assert result.trades[0]["close_reason"] == "breakeven"
        assert result.trades[0]["exit_time"] == base + timedelta(minutes=90)

    def test_skipped_scan_preserves_existing_breakeven_clock(self):
        """When skip_if_positions_open stops a scan, production exits before rule
        creation. The backtest must keep the previous active breakeven timer.
        """
        from backend.services.backtest_engine import BacktestEngine

        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        second = base + timedelta(minutes=30)
        signals = [
            self._signal("s1", base),
            self._signal("s2", second),
        ]

        result = BacktestEngine().run(
            _laconfig(
                take_profit_pct=900.0,
                stop_loss_pct=900.0,
                breakeven_timeout_hours=1.0,
                skip_if_positions_open=True,
            ),
            signals,
            {"CARRYUSDT": self._flat_klines(base)},
        )

        assert len(result.trades) == 1
        assert result.trades[0]["close_reason"] == "breakeven"
        assert result.trades[0]["exit_time"] == base + timedelta(minutes=60)


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


class TestStaleEntryNotFabricated:
    """An entry must NEVER be fabricated from a STALE candle. If a symbol's cached
    candles all end BEFORE the signal time (partial/truncated coverage), there is no
    real price at which the trade could have filled — production would have no fill
    either. The engine must SKIP the signal (count it as no-kline) instead of filling
    at the last stale candle's close.

    Regression: a backtest read partial cache (e.g. EIGEN had candles ending ~2h before
    the scan), and `_open_position` fell back to `symbol_klines[-1]["close"]`, filling a
    short at a 2h-stale price (0.161 vs the real 0.178). That wrong entry cascaded into
    wrong PnL and a held-to-max_duration position that skipped later scans.
    """

    BASE = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    def _signal_at(self, t):
        return [{"id": 1, "ticker": "BTCUSDT", "direction": "sell", "confidence": "high",
                 "score": 8, "signal_time": t, "scan_id": "s1",
                 "signal_source": "structured", "analysis_price": 100.0}]

    def test_no_candle_at_or_after_signal_is_skipped_not_fabricated(self):
        """Candles cover 12:00–12:30 but the signal fires at 14:00 (cache truncated
        before the signal). There is NO bar with open_time >= 14:00, so the engine must
        skip the trade — not fill at the last (12:30) close."""
        from backend.services.backtest_engine import BacktestEngine
        candles = [
            {"open_time": self.BASE + timedelta(minutes=i * 5), "open": 100.0,
             "high": 100.0, "low": 100.0, "close": 100.0, "volume": 100.0}
            for i in range(7)  # 12:00 .. 12:30
        ]
        sig_t = self.BASE + timedelta(hours=2)  # 14:00 — after all candles
        result = BacktestEngine().run(_laconfig(), self._signal_at(sig_t), {"BTCUSDT": candles})
        assert result.trades == [], (
            "engine fabricated a fill from a stale pre-signal candle instead of skipping; "
            f"got {result.trades}"
        )
        assert result.filter_stats.get("signals_no_kline", 0) == 1, (
            "a signal with no candle at/after its time must be counted as no-kline"
        )

    def test_forward_candle_present_still_fills_normally(self):
        """Control: when a candle DOES exist at/after the signal time, the trade fills
        as before (the new guard must not block legitimate entries)."""
        from backend.services.backtest_engine import BacktestEngine
        candles = [
            {"open_time": self.BASE + timedelta(minutes=i * 5), "open": 100.0,
             "high": 100.0, "low": 100.0, "close": 100.0, "volume": 100.0}
            for i in range(20)
        ]
        sig_t = self.BASE + timedelta(minutes=3, seconds=47)  # 12:03:47 → fills 12:05
        result = BacktestEngine().run(_laconfig(), self._signal_at(sig_t), {"BTCUSDT": candles})
        assert len(result.trades) == 1
        assert result.trades[0]["entry_price"] == pytest.approx(100.0)


class TestIntrabarEquityDrawdown:

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

    def test_smart_drawdown_ignores_intrabar_wick_when_close_equity_holds(self):
        from backend.services.backtest_engine import BacktestEngine
        base = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        candles = []
        for i in range(8):
            t = base + timedelta(minutes=i * 5)
            if i == 5:
                candles.append({"open_time": t, "open": 100.0, "high": 105.0, "low": 100.0, "close": 100.0, "volume": 100.0})
            else:
                candles.append({"open_time": t, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 100.0})

        cfg = self._cfg()
        cfg["smart_drawdown_close"] = True
        result = BacktestEngine().run(cfg, self._short_signal(), {"BTCUSDT": candles})

        assert len(result.trades) == 1
        assert result.trades[0]["close_reason"] != "equity_drop_smart"

    def test_smart_drawdown_closes_losers_at_sampled_close(self):
        from backend.services.backtest_engine import BacktestEngine
        base = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        candles = []
        for i in range(8):
            t = base + timedelta(minutes=i * 5)
            if i == 5:
                candles.append({"open_time": t, "open": 100.0, "high": 106.0, "low": 100.0, "close": 105.0, "volume": 100.0})
            else:
                candles.append({"open_time": t, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 100.0})

        cfg = self._cfg()
        cfg["smart_drawdown_close"] = True
        result = BacktestEngine().run(cfg, self._short_signal(), {"BTCUSDT": candles})

        trade = result.trades[0]
        assert trade["close_reason"] == "equity_drop_smart"
        assert trade["exit_price"] == pytest.approx(105.0)


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

    def test_drilled_price_does_not_change_trade_lifecycle(self):
        """Entry drill is PRICE-ONLY: it refines the fill price from the signal-bar 1m
        open but keeps the 5m next-bar-open LIFECYCLE, so a position opens/closes on the
        same bars as the 5m engine (preserving the skip_if_positions_open cascade and
        trade count). Here: the drilled fill price differs, but the position is still
        evaluated from the 12:05 bar onward — identical close timing to no-drill."""
        from backend.services.backtest_engine import BacktestEngine
        klines = self._klines()
        signal_bar = self.BASE  # 12:00 contains the 12:03:47 signal
        fine = {"BTCUSDT": {_fine_key(signal_bar): [
            {"open_time": signal_bar + timedelta(minutes=m), "open": 97.0 if m == 4 else 100.0,
             "high": 110.0, "low": 97.0, "close": 110.0, "volume": 10.0}
            for m in range(5)
        ]}}
        drilled = BacktestEngine().run(self._cfg(), self._signal(), klines, fine_klines=fine)
        plain = BacktestEngine().run(self._cfg(), self._signal(), klines)
        assert len(drilled.trades) == len(plain.trades) == 1
        # price drilled to the 12:04 1m open (97), distinct from the 5m fill...
        assert drilled.trades[0]["entry_price"] == pytest.approx(97.0)
        # ...but the lifecycle (entry/exit TIMES) is unchanged vs no-drill.
        assert drilled.trades[0]["entry_time"] == plain.trades[0]["entry_time"]
        assert drilled.trades[0]["exit_time"] == plain.trades[0]["exit_time"]

    def test_entry_fills_in_signal_bar_not_next_bar(self):
        """Production fills at the scan instant (mid-bar); the 5m engine defers to the
        NEXT bar's open. With a 1m window on the SIGNAL's own bar, drill-down must fill
        there (one 5m bar earlier) — matching production's actual fill timing."""
        from backend.services.backtest_engine import BacktestEngine
        # signal at 12:03:47 → its containing 5m bar is 12:00. Without drill the engine
        # would fill at the 12:05 bar open. With a 1m window on the 12:00 bar, it fills
        # at the 1m candle >= 12:03:47 there (12:04, open 97).
        sig = [{"id": 1, "ticker": "BTCUSDT", "direction": "buy", "confidence": "high",
                "score": 8, "signal_time": self.BASE + timedelta(minutes=3, seconds=47),
                "scan_id": "s1", "signal_source": "structured", "analysis_price": 100.0}]
        out = []
        for i in range(20):
            t = self.BASE + timedelta(minutes=i * 5)
            # 12:00 bar opens 100; 12:05 bar opens 110 (distinct, so we can tell which won)
            out.append({"open_time": t, "open": 100.0 if i == 0 else 110.0,
                        "high": 110.0, "low": 100.0, "close": 110.0, "volume": 100.0})
        signal_bar = self.BASE  # 12:00 contains 12:03:47
        fine = {"BTCUSDT": {_fine_key(signal_bar): [
            {"open_time": signal_bar + timedelta(minutes=m),
             "open": 97.0 if m == 4 else 100.0, "high": 110.0, "low": 97.0, "close": 110.0, "volume": 10.0}
            for m in range(5)
        ]}}
        r = BacktestEngine().run(self._cfg(), sig, {"BTCUSDT": out}, fine_klines=fine)
        assert len(r.trades) == 1
        # fills at the 12:04 1m open (97) in the SIGNAL bar — not the 12:05 5m open (110).
        assert r.trades[0]["entry_price"] == pytest.approx(97.0), (
            f"expected signal-bar 1m fill 97, got {r.trades[0]['entry_price']}"
        )

    def test_equity_drop_uses_drilled_exchange_fill_price(self):
        """Production wallet equity is based on the exchange avgPrice, so equity close
        rules must use the simulated actual fill. A drilled short entry that is much
        more favorable should delay/avoid a drawdown close that the synthetic 5m fill
        would have triggered."""
        from backend.services.backtest_engine import BacktestEngine
        # short, 10x, capital 100% → +5% adverse = 50% drawdown. drawdown threshold 50%.
        cfg = _laconfig(capital_pct=100.0, leverage=10, take_profit_pct=900.0,
                        stop_loss_pct=900.0, max_drawdown_pct=50.0, smart_drawdown_close=False,
                        fee_rate_pct=0.0, slippage_bps=0)
        sig = [{"id": 1, "ticker": "BTCUSDT", "direction": "sell", "confidence": "high",
                "score": 8, "signal_time": self.BASE + timedelta(minutes=3, seconds=47),
                "scan_id": "s1", "signal_source": "structured", "analysis_price": 100.0}]
        out = []
        for i in range(10):
            t = self.BASE + timedelta(minutes=i * 5)
            if i == 1:    # entry bar (12:05) opens 100
                out.append({"open_time": t, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 100.0})
            elif i == 3:  # price rises to 106 (a >50% drawdown for the short) and closes there
                out.append({"open_time": t, "open": 100.0, "high": 106.0, "low": 100.0, "close": 106.0, "volume": 100.0})
            else:
                out.append({"open_time": t, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 100.0})
        # drilled entry in the SIGNAL bar (12:00) at a much HIGHER short fill (110 = more
        # favorable for a short), which would shrink the measured drawdown if (wrongly)
        # used by the equity rule.
        signal_bar = self.BASE
        fine = {"BTCUSDT": {_fine_key(signal_bar): [
            {"open_time": signal_bar + timedelta(minutes=m), "open": 110.0,
             "high": 110.0, "low": 110.0, "close": 110.0, "volume": 10.0}
            for m in range(5)
        ]}}
        plain = BacktestEngine().run(cfg, sig, {"BTCUSDT": out})
        drilled = BacktestEngine().run(cfg, sig, {"BTCUSDT": out}, fine_klines=fine)
        assert len(plain.trades) == len(drilled.trades) == 1
        assert plain.trades[0]["close_reason"] == "equity_drop"
        assert drilled.trades[0]["close_reason"] == "backtest_end"
        assert plain.trades[0]["exit_time"] != drilled.trades[0]["exit_time"]
        assert drilled.trades[0]["entry_price"] == pytest.approx(110.0)
        assert plain.trades[0]["entry_price"] == pytest.approx(100.0)


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


def _five_m(open_time, o, h, l, c, vol=100.0):
    return {"open_time": open_time, "open": o, "high": h, "low": l, "close": c, "volume": vol}


class TestPortfolioEquityOneMinuteWalk:
    """1-minute PORTFOLIO-EQUITY walk: when a 5m bar's equity rule (drawdown / smart /
    rise / close_on_profit) WOULD fire AND a full-book 1m window exists for that bar,
    the engine walks the bar minute-by-minute and fires at the FIRST minute the *true
    simultaneous* account equity crosses — stamping that minute's time + price — instead
    of the 5m bar boundary using each symbol's own-bar adverse extreme.

    Rationale (verified against production): the 5m drawdown values every open position
    at ITS OWN bar adverse extreme and sums them — a synchronized-worst-case that (a)
    stamps the close at the bar open using ~end-of-bar prices (look-ahead) and (b) can
    fabricate a drawdown that never simultaneously happened. The 1m walk fixes both.

    Gating preserves the golden guarantee: with NO fine windows the engine is
    byte-identical to the 5m path. The walk only ever REFINES a breach the 5m gate
    already flagged (it can never miss one: Σ own-bar-worst ≤ min-minute simultaneous).
    """

    BASE = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    def _two_short_signals(self):
        # Two equal-score shorts in ONE scan → opened together, evaluated on a shared
        # unified timeline so the portfolio-equity sum spans both.
        t = self.BASE + timedelta(minutes=3, seconds=47)
        return [
            {"id": 1, "ticker": "AAA", "direction": "sell", "confidence": "high",
             "score": 8, "signal_time": t, "scan_id": "s1",
             "signal_source": "structured", "analysis_price": 100.0},
            {"id": 2, "ticker": "BBB", "direction": "sell", "confidence": "high",
             "score": 8, "signal_time": t, "scan_id": "s1",
             "signal_source": "structured", "analysis_price": 100.0},
        ]

    def _cfg(self, **ov):
        # 2 trades, each 50% capital @ 10x. A +5% adverse move on a short = +50% of that
        # leg's margin loss. With both legs equal, a simultaneous +6% on BOTH = ~60%
        # book drawdown. max_drawdown 50% (non-smart → closes ALL). Huge TP/SL so only
        # the equity rule can close. fee/slip 0 for exact arithmetic.
        base = dict(capital_pct=50.0, leverage=10, take_profit_pct=900.0,
                    stop_loss_pct=900.0, max_drawdown_pct=50.0, smart_drawdown_close=False,
                    max_trades=2, fee_rate_pct=0.0, slippage_bps=0, execution_mode="batch")
        base.update(ov)
        return _laconfig(**base)

    def _klines(self, breach_bar_idx=4):
        """Flat-100 5m series for AAA and BBB except the breach bar, whose 5m HIGH = 106
        (a +6% adverse move for a short) but whose 5m CLOSE returns to 100. At 5m the
        own-bar-high sum fires drawdown; the 1m detail (per test) decides the truth."""
        aaa, bbb = [], []
        for i in range(12):
            t = self.BASE + timedelta(minutes=i * 5)
            if i == 1:        # 12:05 entry bar — flat 100 (fills at open 100)
                aaa.append(_five_m(t, 100.0, 100.0, 100.0, 100.0))
                bbb.append(_five_m(t, 100.0, 100.0, 100.0, 100.0))
            elif i == breach_bar_idx:
                aaa.append(_five_m(t, 100.0, 106.0, 100.0, 100.0))
                bbb.append(_five_m(t, 100.0, 106.0, 100.0, 100.0))
            else:
                aaa.append(_five_m(t, 100.0, 100.0, 100.0, 100.0))
                bbb.append(_five_m(t, 100.0, 100.0, 100.0, 100.0))
        return {"AAA": aaa, "BBB": bbb}, self.BASE + timedelta(minutes=breach_bar_idx * 5)

    def _window(self, bar_open, aaa_minutes, bbb_minutes):
        """Build a full-book 1m fine_klines dict for the breach bar. *_minutes are lists
        of 5 (high, low) tuples for minutes 0..4. open=close=low so a short's adverse
        extreme is the minute's HIGH and the simultaneous mark is the minute's close."""
        def seq(mins):
            out = []
            for m, (hi, lo) in enumerate(mins):
                out.append(_five_m(bar_open + timedelta(minutes=m), lo, hi, lo, lo, 10.0))
            return out
        return {
            "AAA": {int(bar_open.timestamp()): seq(aaa_minutes)},
            "BBB": {int(bar_open.timestamp()): seq(bbb_minutes)},
        }

    def test_drawdown_fires_at_true_one_minute_crossing_not_bar_open(self):
        """Both shorts spike to 106 on the SAME minute (minute 3) → true simultaneous
        equity DOES breach 50%, but only at minute 3. The 5m path would stamp the close
        at the bar OPEN (minute 0); the 1m walk must stamp it at minute 3 and at price
        106 (the adverse extreme of the crossing minute)."""
        from backend.services.backtest_engine import BacktestEngine
        klines, bar = self._klines()
        flat = (100.0, 100.0)
        spike = (106.0, 100.0)
        mins = [flat, flat, flat, spike, flat]  # both spike together at minute 3
        fine = self._window(bar, mins, mins)
        r = BacktestEngine().run(self._cfg(), self._two_short_signals(), klines, fine_klines=fine)
        drops = [t for t in r.trades if t["close_reason"] == "equity_drop"]
        assert len(drops) == 2, (
            f"expected both legs closed by equity_drop, got {[t['close_reason'] for t in r.trades]}"
        )
        # Stamped at minute 3 (12:23), not the bar open (12:20).
        assert all(t["exit_time"] == bar + timedelta(minutes=3) for t in drops), (
            f"equity_drop should stamp the true 1m crossing minute (12:23), got "
            f"{[t['exit_time'] for t in drops]}"
        )
        # Closed at the crossing minute's adverse extreme (106), not the 5m close (100).
        assert all(t["exit_price"] == pytest.approx(106.0) for t in drops)

    def test_phantom_synchronized_wick_does_not_fire(self):
        """AAA spikes to 106 ONLY at minute 1; BBB spikes to 106 ONLY at minute 3. They
        never spike together, so the true simultaneous book drawdown peaks at ~30% (one
        leg at +6%, the other flat) — under the 50% threshold. But the 5m own-bar-high
        sum sees BOTH at 106 → ~60% → the 5m path fires a PHANTOM drawdown. The 1m walk
        must NOT close either position."""
        from backend.services.backtest_engine import BacktestEngine
        klines, bar = self._klines()
        flat = (100.0, 100.0)
        spike = (106.0, 100.0)
        aaa_mins = [flat, spike, flat, flat, flat]   # AAA worst at minute 1
        bbb_mins = [flat, flat, flat, spike, flat]   # BBB worst at minute 3
        fine = self._window(bar, aaa_mins, bbb_mins)
        r = BacktestEngine().run(self._cfg(), self._two_short_signals(), klines, fine_klines=fine)
        drop_or_smart = [t for t in r.trades if t["close_reason"] in ("equity_drop", "equity_drop_smart")]
        assert not drop_or_smart, (
            "5m synchronized-wick fired a phantom drawdown the 1m simultaneous path never "
            f"reached; got closes {[(t['symbol'], t['close_reason']) for t in r.trades]}"
        )

    def test_no_fine_data_fires_5m_synchronized_drawdown_unchanged(self):
        """Golden control: the SAME phantom setup WITHOUT fine data keeps the legacy 5m
        behaviour (fires on the own-bar-high sum). Proves the walk is the only thing that
        changes the phantom outcome — the 5m path is untouched when no 1m is injected."""
        from backend.services.backtest_engine import BacktestEngine
        klines, bar = self._klines()
        r = BacktestEngine().run(self._cfg(), self._two_short_signals(), klines)
        drops = [t for t in r.trades if t["close_reason"] == "equity_drop"]
        assert len(drops) == 2, (
            "without 1m data the 5m own-bar-high drawdown must still fire (legacy behaviour)"
        )
        assert all(t["exit_time"] == bar for t in drops), "5m path stamps at the bar open"

    def test_partial_book_coverage_falls_back_to_5m(self):
        """The walk needs EVERY open symbol's 1m window (equity is a book-wide sum). If
        only ONE symbol has a 1m window for the breach bar, the engine must fall back to
        the 5m evaluation for that bar (fail-soft) — here that means the 5m synchronized
        drawdown still fires at the bar open, exactly as the no-fine path."""
        from backend.services.backtest_engine import BacktestEngine
        klines, bar = self._klines()
        flat = (100.0, 100.0)
        spike = (106.0, 100.0)
        full = self._window(bar, [flat, flat, flat, spike, flat], [flat, flat, flat, spike, flat])
        partial = {"AAA": full["AAA"]}  # BBB window missing → not full-book
        r = BacktestEngine().run(self._cfg(), self._two_short_signals(), klines, fine_klines=partial)
        drops = [t for t in r.trades if t["close_reason"] == "equity_drop"]
        assert len(drops) == 2, "partial-book coverage must fall back to the 5m drawdown"
        assert all(t["exit_time"] == bar for t in drops), (
            "fallback must use the 5m bar-open stamp, not a partial 1m walk"
        )

    def _rise_cfg(self, **ov):
        # profit_pct target goal → EQUITY_RISE_PCT. Two shorts, +goal% book gain closes
        # all. Large drawdown so only the rise rule can fire.
        base = dict(capital_pct=50.0, leverage=10, take_profit_pct=900.0,
                    stop_loss_pct=900.0, max_drawdown_pct=100.0, smart_drawdown_close=False,
                    max_trades=2, fee_rate_pct=0.0, slippage_bps=0, execution_mode="batch",
                    target_goal_type="profit_pct", target_goal_value=50.0)
        base.update(ov)
        return _laconfig(**base)

    def _rise_klines(self, gain_bar_idx=4):
        """Both shorts profit: the gain bar's 5m LOW = 95 (a −5% move = +50% margin gain
        per leg → ~+50% book at 50%/10x). 5m CLOSE returns to 100 (gain only intrabar)."""
        aaa, bbb = [], []
        for i in range(12):
            t = self.BASE + timedelta(minutes=i * 5)
            if i == 1:
                aaa.append(_five_m(t, 100.0, 100.0, 100.0, 100.0))
                bbb.append(_five_m(t, 100.0, 100.0, 100.0, 100.0))
            elif i == gain_bar_idx:
                aaa.append(_five_m(t, 100.0, 100.0, 95.0, 100.0))
                bbb.append(_five_m(t, 100.0, 100.0, 95.0, 100.0))
            else:
                aaa.append(_five_m(t, 100.0, 100.0, 100.0, 100.0))
                bbb.append(_five_m(t, 100.0, 100.0, 100.0, 100.0))
        return {"AAA": aaa, "BBB": bbb}, self.BASE + timedelta(minutes=gain_bar_idx * 5)

    def test_equity_rise_fires_at_true_one_minute_crossing(self):
        """The rise rule is evaluated on the 5m CLOSE today, so an intrabar +50% spike
        that recovers by close is missed at this bar (caught only later/at force-close).
        With a full-book 1m window the walk must fire the rise at the first minute the
        true simultaneous equity crosses +50%, stamped at that minute and its price."""
        from backend.services.backtest_engine import BacktestEngine
        klines, bar = self._rise_klines()
        flat = (100.0, 100.0)
        gain = (100.0, 95.0)  # (high, low): short gains at low=95
        mins = [flat, flat, gain, flat, flat]  # both reach +50% together at minute 2
        fine = self._window(bar, mins, mins)
        r = BacktestEngine().run(self._rise_cfg(), self._two_short_signals(), klines, fine_klines=fine)
        rises = [t for t in r.trades if t["close_reason"] == "equity_rise"]
        assert len(rises) == 2, (
            f"expected both legs closed by equity_rise at the 1m crossing, got "
            f"{[(t['symbol'], t['close_reason'], t['exit_time']) for t in r.trades]}"
        )
        assert all(t["exit_time"] == bar + timedelta(minutes=2) for t in rises), (
            f"rise should stamp the 1m crossing minute (12:22), got {[t['exit_time'] for t in rises]}"
        )
        assert all(t["exit_price"] == pytest.approx(95.0) for t in rises)

    def test_walk_is_byte_identical_without_fine_data(self):
        """Golden: a full multi-symbol equity-rule run with fine_klines=None / {} must
        equal the run that never passes the param — the walk is fully inert without 1m."""
        from backend.services.backtest_engine import BacktestEngine
        klines, _ = self._klines()
        sigs = self._two_short_signals()
        a = BacktestEngine().run(self._cfg(), sigs, klines)
        b = BacktestEngine().run(self._cfg(), sigs, klines, fine_klines=None)
        c = BacktestEngine().run(self._cfg(), sigs, klines, fine_klines={})
        assert a.trades == b.trades == c.trades
        assert a.metrics.get("net_profit") == b.metrics.get("net_profit") == c.metrics.get("net_profit")
