"""Pydantic schemas for the backtesting system."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class ScanSource(BaseModel):
    """Defines which historical scan results to use for backtesting."""

    mode: Literal["schedule", "date_range", "explicit"]
    schedule_id: Optional[str] = None
    scan_ids: Optional[list[str]] = None

    @field_validator("scan_ids")
    @classmethod
    def validate_scan_ids(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is not None and len(v) > 500:
            raise ValueError("Maximum 500 scan_ids allowed")
        return v

    @model_validator(mode="after")
    def validate_mode_fields(self) -> "ScanSource":
        if self.mode == "schedule" and not self.schedule_id:
            raise ValueError("schedule_id is required when mode='schedule'")
        if self.mode == "explicit" and not self.scan_ids:
            raise ValueError("scan_ids is required when mode='explicit'")
        return self


class BacktestCreateRequest(BaseModel):
    """Request schema for creating a new backtest run."""

    # Backtest-specific fields
    starting_capital: float = Field(..., gt=0, le=100_000_000)
    date_range_start: datetime
    date_range_end: datetime
    scan_source: ScanSource
    simulation_interval: Literal["5m", "15m", "1h", "4h"] = "5m"
    fee_rate_pct: float = Field(default=0.055, ge=0, le=1.0)
    slippage_bps: int = Field(default=2, ge=0, le=50)
    funding_rate_model: Literal["none", "fixed_8h"] = "none"
    funding_rate_fixed_pct: float = Field(default=0.01, ge=-0.5, le=0.5)

    # AutoTradeConfig fields (trade decision params)
    direction: Literal["straight", "reverse"] = "straight"
    leverage: int = Field(default=20, ge=1, le=125)
    capital_pct: float = Field(default=5.0, gt=0, le=100)
    take_profit_pct: float = Field(default=150.0, gt=0, le=1000)
    stop_loss_pct: float = Field(default=100.0, gt=0, le=1000)
    min_score: float = Field(default=0.0, ge=-10, le=10)
    confidence_filter: Literal["any", "high", "moderate", "low"] = "any"
    signal_sides: Literal["both", "buy", "sell"] = "both"
    max_trades: int = Field(default=999, ge=1, le=999)
    execution_mode: Literal["immediate", "batch"] = "immediate"
    fill_to_max_trades: bool = False
    skip_if_positions_open: bool = False
    max_same_direction: Optional[int] = Field(default=None, ge=1, le=100)
    max_same_sector: Optional[int] = Field(default=None, ge=1, le=50)
    symbol_blacklist: Optional[list[str]] = Field(default=None, max_length=200)
    symbol_whitelist: Optional[list[str]] = Field(default=None, max_length=200)
    max_signal_age_minutes: Optional[int] = Field(default=None, ge=1)
    max_price_drift_pct: Optional[float] = Field(default=None, ge=0.1, le=50)

    # Close rules
    max_drawdown_pct: float = Field(default=100.0, gt=0, le=100)
    smart_drawdown_close: bool = False
    breakeven_timeout_hours: Optional[float] = Field(default=None, ge=0.1, le=720)
    max_trade_duration_hours: Optional[float] = Field(default=None, ge=0.1, le=720)
    trailing_profit_pct: Optional[float] = Field(default=None, ge=0.1, le=50)
    close_on_profit_pct: Optional[float] = Field(default=None, ge=0.1, le=100)

    # Target goal (used by close_on_profit_pct formula)
    target_goal_type: Optional[Literal["trade_count", "profit_pct"]] = None
    target_goal_value: Optional[float] = Field(default=None, gt=0)

    # Adaptive blacklist
    adaptive_blacklist_enabled: bool = False
    adaptive_blacklist_min_trades: int = Field(default=5, ge=1, le=100)
    adaptive_blacklist_max_win_rate: float = Field(default=30.0, ge=0, le=100)
    adaptive_blacklist_lookback_hours: int = Field(default=48, ge=1, le=720)

    @model_validator(mode="after")
    def validate_dates(self) -> "BacktestCreateRequest":
        if self.date_range_end <= self.date_range_start:
            raise ValueError("date_range_end must be after date_range_start")
        days = (self.date_range_end - self.date_range_start).days
        if days > 365:
            raise ValueError(f"Date range cannot exceed 365 days (got {days})")
        return self

    @model_validator(mode="after")
    def validate_cross_fields(self) -> "BacktestCreateRequest":
        # SL% cannot exceed liquidation distance
        if self.stop_loss_pct / self.leverage >= 100:
            raise ValueError(
                f"stop_loss_pct ({self.stop_loss_pct}) at leverage {self.leverage} "
                f"exceeds liquidation distance"
            )
        # breakeven_timeout must be < max_duration if both set
        if (
            self.breakeven_timeout_hours is not None
            and self.max_trade_duration_hours is not None
            and self.breakeven_timeout_hours >= self.max_trade_duration_hours
        ):
            raise ValueError(
                "breakeven_timeout_hours must be less than max_trade_duration_hours"
            )
        return self


class BacktestRunResponse(BaseModel):
    """Response schema for a backtest run."""

    id: str
    status: str
    config: dict[str, Any]
    scan_source: dict[str, Any]
    progress_pct: int = 0
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    results: Optional[dict[str, Any]] = None


class BacktestTradeResponse(BaseModel):
    """Response schema for a single simulated trade."""

    id: int
    symbol: str
    side: str
    entry_price: float
    exit_price: Optional[float] = None
    qty: float
    leverage: int
    entry_time: datetime
    exit_time: Optional[datetime] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    fees_paid: Optional[float] = None
    close_reason: Optional[str] = None
    mfe_pct: Optional[float] = None
    mae_pct: Optional[float] = None
    signal_score: Optional[int] = None
    signal_confidence: Optional[str] = None
    scan_id: Optional[str] = None


class BacktestResultsResponse(BaseModel):
    """Response with full backtest results."""

    run_id: str
    metrics: dict[str, Any]
    equity_curve: list[dict[str, Any]]
    summary: dict[str, Any] = {}
    warnings: list[str] = []


class BacktestCompareResponse(BaseModel):
    """Response for comparing multiple backtest runs."""

    runs: list[dict[str, Any]]


# --- Engine output dataclass (not Pydantic — used internally) ---


@dataclass
class SimulationResult:
    """Output from the backtest simulation engine."""

    trades: list[dict[str, Any]]
    equity_curve: list[dict[str, Any]]
    metrics: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    filter_stats: dict[str, Any] = field(default_factory=dict)
