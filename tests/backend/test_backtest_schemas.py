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
            # Regime Multi-Strategy fields are now accepted by the backtester (so it can
            # validate F1/F2/F3 before live funding) and MUST default identically to
            # production, or a backtest wouldn't reflect real trading.
            "regime_filter_enabled", "session_filter_enabled", "session_blocked_hours_utc",
            "session_allowed_hours_utc", "btc_vol_filter_enabled", "btc_vol_min_threshold",
            "btc_vol_max_threshold", "btc_vol_interval", "btc_vol_lookback_candles",
            "mean_reversion_enabled", "mr_short_enabled", "mr_long_enabled", "mr_regime",
            "mr_mean_period", "mr_mean_interval", "mr_target_capture_pct", "mr_tight_stop_pct",
            "mr_time_stop_minutes", "mr_min_edge_pct", "mr_extreme_min_abs_score",
            "mr_capital_pct", "mr_leverage", "mr_max_trades", "strategy_cohort",
            "regime_staleness_minutes", "regime_volatile_atr", "regime_trend_ema_dist_pct",
        ]
        for field in shared:
            assert getattr(bt, field) == getattr(prod, field), (
                f"backtest default for {field!r} ({getattr(bt, field)!r}) diverges from "
                f"production AutoTradeConfig ({getattr(prod, field)!r}) — they must match "
                "for real-world-faithful results"
            )

    def test_accepts_regime_fields(self):
        """The backtester now ACCEPTS F1/F2/F3 fields (was: 422'd them) so the regime
        features can be validated on historical data before live funding."""
        from backend.schemas.backtest_schemas import BacktestCreateRequest, ScanSource
        req = BacktestCreateRequest(
            starting_capital=10000.0,
            date_range_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            date_range_end=datetime(2026, 1, 31, tzinfo=timezone.utc),
            scan_source=ScanSource(mode="date_range"),
            regime_filter_enabled=True,
            session_filter_enabled=True,
            session_blocked_hours_utc=[1, 6, 7, 8],
            btc_vol_filter_enabled=True,
            btc_vol_min_threshold=0.8,
            btc_vol_max_threshold=3.0,
            mean_reversion_enabled=True,
            mr_short_enabled=True,
            mr_long_enabled=True,
            strategy_cohort="mean_reversion",
            mr_capital_pct=2.0,
            mr_leverage=10,
            mr_time_stop_minutes=120,
        )
        assert req.mean_reversion_enabled is True
        assert req.strategy_cohort == "mean_reversion"
        assert req.session_blocked_hours_utc == [1, 6, 7, 8]
        assert req.mr_long_enabled is True

    def test_regime_validators_mirror_production(self):
        """The 3 cross-field regime validators (session-exclusive, vol-band, mr-direction)
        apply in the backtest schema exactly as in AutoTradeConfig."""
        from backend.schemas.backtest_schemas import BacktestCreateRequest, ScanSource
        base = dict(
            starting_capital=10000.0,
            date_range_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            date_range_end=datetime(2026, 1, 31, tzinfo=timezone.utc),
            scan_source=ScanSource(mode="date_range"),
        )
        # session blocked + allowed are mutually exclusive
        with pytest.raises(ValidationError, match="mutually exclusive"):
            BacktestCreateRequest(**base, session_blocked_hours_utc=[1], session_allowed_hours_utc=[2])
        # vol band must be lo < hi
        with pytest.raises(ValidationError, match="btc_vol_min_threshold must be"):
            BacktestCreateRequest(**base, btc_vol_min_threshold=3.0, btc_vol_max_threshold=1.0)
        # MR enabled requires at least one direction
        with pytest.raises(ValidationError, match="at least one of"):
            BacktestCreateRequest(**base, mean_reversion_enabled=True,
                                  mr_short_enabled=False, mr_long_enabled=False)

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


    def test_close_on_profit_requires_target_goal_value(self):
        """close_on_profit_pct without target_goal_value must be REJECTED — production
        gates close_on_profit on `close_pct and target_goal` and the live request schema
        requires the goal value. The effective threshold is
        (close_on_profit_pct/100)·target_goal_value, undefined without the goal."""
        from backend.schemas.backtest_schemas import BacktestCreateRequest, ScanSource
        with pytest.raises(ValidationError):
            BacktestCreateRequest(
                starting_capital=10000.0,
                date_range_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
                date_range_end=datetime(2026, 1, 31, tzinfo=timezone.utc),
                scan_source=ScanSource(mode="date_range"),
                close_on_profit_pct=50.0,  # no target_goal_value → invalid
            )

    def test_close_on_profit_with_target_goal_value_accepted(self):
        """close_on_profit_pct WITH target_goal_value is valid."""
        from backend.schemas.backtest_schemas import BacktestCreateRequest, ScanSource
        req = BacktestCreateRequest(
            starting_capital=10000.0,
            date_range_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            date_range_end=datetime(2026, 1, 31, tzinfo=timezone.utc),
            scan_source=ScanSource(mode="date_range"),
            close_on_profit_pct=50.0,
            target_goal_value=10.0,
        )
        assert req.close_on_profit_pct == 50.0
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
