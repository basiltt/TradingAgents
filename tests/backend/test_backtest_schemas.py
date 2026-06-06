"""Tests for backtest Pydantic schemas — validation edge cases."""

import pytest
from datetime import datetime, timezone, timedelta
from pydantic import ValidationError


class TestBacktestCreateRequest:
    """Test BacktestCreateRequest validation."""

    def test_valid_minimal_config(self):
        from backend.schemas.backtest_schemas import BacktestCreateRequest, ScanSource
        req = BacktestCreateRequest(
            starting_capital=10000.0,
            date_range_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            date_range_end=datetime(2026, 1, 31, tzinfo=timezone.utc),
            scan_source=ScanSource(mode="date_range"),
        )
        assert req.starting_capital == 10000.0
        assert req.leverage == 20  # default
        assert req.take_profit_pct == 150.0  # default
        assert req.fee_rate_pct == 0.055  # default

    def test_defaults_match_production_autotradeconfig(self):
        """The backtest's defaults for the shared AutoTradeConfig fields MUST equal
        production's AutoTradeConfig defaults, so a backtest reflects ~100% real-world
        trading (and a raw-API caller omitting a field gets production behavior, not an
        arbitrary preset). Guards against the two schemas drifting apart.
        """
        from backend.schemas.backtest_schemas import BacktestCreateRequest, ScanSource
        from backend.schemas import AutoTradeConfig

        bt = BacktestCreateRequest(
            starting_capital=10000.0,
            date_range_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            date_range_end=datetime(2026, 1, 31, tzinfo=timezone.utc),
            scan_source=ScanSource(mode="date_range"),
        )
        prod = AutoTradeConfig(account_id="acct-1")  # production defaults

        # Every field the backtest shares with production must default identically.
        shared = [
            "direction", "leverage", "capital_pct", "take_profit_pct", "stop_loss_pct",
            "min_score", "confidence_filter", "signal_sides", "max_trades",
            "execution_mode", "fill_to_max_trades", "skip_if_positions_open",
            "max_drawdown_pct", "smart_drawdown_close", "max_same_direction",
            "max_same_sector", "max_signal_age_minutes", "max_price_drift_pct",
            "trailing_profit_pct", "breakeven_timeout_hours", "max_trade_duration_hours",
            "close_on_profit_pct", "target_goal_type", "target_goal_value",
            "symbol_blacklist", "symbol_whitelist", "adaptive_blacklist_enabled",
        ]
        for field in shared:
            assert getattr(bt, field) == getattr(prod, field), (
                f"backtest default for {field!r} ({getattr(bt, field)!r}) diverges from "
                f"production AutoTradeConfig ({getattr(prod, field)!r}) — they must match "
                "for real-world-faithful results"
            )

    def test_rejects_zero_capital(self):
        from backend.schemas.backtest_schemas import BacktestCreateRequest, ScanSource
        with pytest.raises(ValidationError):
            BacktestCreateRequest(
                starting_capital=0.0,
                date_range_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
                date_range_end=datetime(2026, 1, 31, tzinfo=timezone.utc),
                scan_source=ScanSource(mode="date_range"),
            )

    def test_rejects_leverage_above_125(self):
        from backend.schemas.backtest_schemas import BacktestCreateRequest, ScanSource
        with pytest.raises(ValidationError):
            BacktestCreateRequest(
                starting_capital=10000.0,
                date_range_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
                date_range_end=datetime(2026, 1, 31, tzinfo=timezone.utc),
                scan_source=ScanSource(mode="date_range"),
                leverage=200,
            )

    def test_rejects_date_range_over_365_days(self):
        from backend.schemas.backtest_schemas import BacktestCreateRequest, ScanSource
        with pytest.raises(ValidationError):
            BacktestCreateRequest(
                starting_capital=10000.0,
                date_range_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                date_range_end=datetime(2025, 6, 1, tzinfo=timezone.utc),  # >365 days
                scan_source=ScanSource(mode="date_range"),
            )

    def test_rejects_end_before_start(self):
        from backend.schemas.backtest_schemas import BacktestCreateRequest, ScanSource
        with pytest.raises(ValidationError):
            BacktestCreateRequest(
                starting_capital=10000.0,
                date_range_start=datetime(2026, 2, 1, tzinfo=timezone.utc),
                date_range_end=datetime(2026, 1, 1, tzinfo=timezone.utc),
                scan_source=ScanSource(mode="date_range"),
            )

    def test_includes_all_autotrade_fields(self):
        from backend.schemas.backtest_schemas import BacktestCreateRequest, ScanSource
        req = BacktestCreateRequest(
            starting_capital=5000.0,
            date_range_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            date_range_end=datetime(2026, 1, 15, tzinfo=timezone.utc),
            scan_source=ScanSource(mode="date_range"),
            direction="reverse",
            leverage=50,
            capital_pct=10.0,
            take_profit_pct=200.0,
            stop_loss_pct=80.0,
            min_score=3.0,
            confidence_filter="moderate",
            signal_sides="buy",
            max_trades=5,
            max_drawdown_pct=15.0,
            trailing_profit_pct=5.0,
            breakeven_timeout_hours=4.0,
            max_trade_duration_hours=24.0,
            target_goal_type="profit_pct",
            target_goal_value=10.0,
            close_on_profit_pct=50.0,
        )
        assert req.direction == "reverse"
        assert req.trailing_profit_pct == 5.0
        assert req.target_goal_value == 10.0


class TestScanSource:
    """Test ScanSource validation."""

    def test_schedule_mode(self):
        from backend.schemas.backtest_schemas import ScanSource
        src = ScanSource(mode="schedule", schedule_id="abc-123")
        assert src.mode == "schedule"
        assert src.schedule_id == "abc-123"

    def test_explicit_mode_with_ids(self):
        from backend.schemas.backtest_schemas import ScanSource
        src = ScanSource(mode="explicit", scan_ids=["id1", "id2"])
        assert len(src.scan_ids) == 2

    def test_explicit_mode_rejects_too_many_ids(self):
        from backend.schemas.backtest_schemas import ScanSource
        with pytest.raises(ValidationError):
            ScanSource(mode="explicit", scan_ids=[f"id-{i}" for i in range(501)])

    def test_schedule_mode_requires_schedule_id(self):
        from backend.schemas.backtest_schemas import ScanSource
        with pytest.raises(ValidationError):
            ScanSource(mode="schedule")  # no schedule_id

    def test_explicit_mode_requires_scan_ids(self):
        from backend.schemas.backtest_schemas import ScanSource
        with pytest.raises(ValidationError):
            ScanSource(mode="explicit")  # no scan_ids


class TestSimulationResult:
    """Test SimulationResult dataclass."""

    def test_creates_with_required_fields(self):
        from backend.schemas.backtest_schemas import SimulationResult
        result = SimulationResult(
            trades=[],
            equity_curve=[],
            metrics={},
            warnings=[],
            filter_stats={},
        )
        assert result.trades == []
        assert result.metrics == {}
