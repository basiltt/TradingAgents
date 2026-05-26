"""AI Account Manager Pydantic schemas — Phase 1 Task 1.2."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, List, Literal, Optional

from pydantic import BaseModel, Field


class AIManagerConfig(BaseModel):
    enabled: bool = False
    risk_tolerance: Literal["conservative", "moderate", "aggressive"] = "moderate"
    evaluation_interval_s: int = Field(default=60, ge=30, le=300)
    max_daily_actions: int = Field(default=30, ge=5, le=100)
    max_hourly_actions: int = Field(default=10, ge=2, le=30)
    max_daily_loss_pct: float = Field(default=5.0, ge=1.0, le=25.0)
    daily_profit_target_pct: Optional[float] = Field(default=None, gt=0.0, le=100.0)
    min_position_age_s: int = Field(default=300, ge=60, le=3600)
    confidence_threshold: float = Field(default=0.7, ge=0.3, le=0.95)
    max_single_decision_loss_pct: float = Field(default=3.0, ge=0.5, le=10.0)
    dry_run: bool = False
    grace_period_s: int = Field(default=0, ge=0, le=30)
    excluded_symbols: List[
        Annotated[str, Field(max_length=20, pattern=r"^[A-Z0-9]{1,20}$")]
    ] = Field(default_factory=list, max_length=50)
    locked_positions: List[
        Annotated[str, Field(max_length=20, pattern=r"^[A-Z0-9]{1,20}$")]
    ] = Field(default_factory=list, max_length=50)
    strategy_version: str = Field(
        default="default", pattern=r"^[a-zA-Z0-9_\-]{1,50}$"
    )
    # Emergency close (non-LLM deterministic fast-path for crash protection)
    emergency_close_enabled: bool = True
    emergency_equity_drop_pct: float = Field(default=10.0, ge=3.0, le=50.0)
    emergency_pnl_velocity_pct: float = Field(default=5.0, ge=2.0, le=20.0)
    auto_enabled: bool = False


class PositionAction(BaseModel):
    symbol: str = Field(pattern=r"^[A-Z0-9]{1,20}$")
    action: Literal["close", "partial_close", "adjust_tp", "adjust_sl", "hold"]
    close_pct: Optional[int] = Field(default=None, ge=1, le=100)
    new_tp: Optional[Decimal] = Field(default=None, gt=0)
    new_sl: Optional[Decimal] = Field(default=None, gt=0)


class AIManagerAction(BaseModel):
    action_type: Literal[
        "HOLD", "FULL_CLOSE", "PARTIAL_CLOSE", "ADJUST_TP", "ADJUST_SL"
    ]
    positions: List[PositionAction]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(max_length=500)
    urgency: Literal["low", "medium", "high", "critical"]


class AIManagerStatus(BaseModel):
    enabled: bool
    state: str
    last_analysis_at: Optional[datetime]
    circuit_breaker: dict
    actions_today: int
    budget_remaining: dict
    degradation_tier: int
    kill_switch: bool


class AIManagerDecisionResponse(BaseModel):
    id: int
    timestamp: datetime
    action_taken: dict
    reasoning: str
    confidence: float
    urgency: str
    execution_result: Optional[dict]
    outcome: Optional[dict]
    outcome_label: Optional[str]


class AIManagerConfigPatch(BaseModel):
    risk_tolerance: Optional[Literal["conservative", "moderate", "aggressive"]] = None
    evaluation_interval_s: Optional[int] = Field(default=None, ge=30, le=300)
    max_daily_actions: Optional[int] = Field(default=None, ge=5, le=100)
    max_hourly_actions: Optional[int] = Field(default=None, ge=2, le=30)
    max_daily_loss_pct: Optional[float] = Field(default=None, ge=1.0, le=25.0)
    daily_profit_target_pct: Optional[float] = Field(default=None, gt=0.0, le=100.0)
    min_position_age_s: Optional[int] = Field(default=None, ge=60, le=3600)
    confidence_threshold: Optional[float] = Field(default=None, ge=0.3, le=0.95)
    max_single_decision_loss_pct: Optional[float] = Field(default=None, ge=0.5, le=10.0)
    dry_run: Optional[bool] = None
    grace_period_s: Optional[int] = Field(default=None, ge=0, le=30)
    excluded_symbols: Optional[
        List[Annotated[str, Field(max_length=20, pattern=r"^[A-Z0-9]{1,20}$")]]
    ] = Field(default=None, max_length=50)
    locked_positions: Optional[
        List[Annotated[str, Field(max_length=20, pattern=r"^[A-Z0-9]{1,20}$")]]
    ] = Field(default=None, max_length=50)
    emergency_close_enabled: Optional[bool] = None
    emergency_equity_drop_pct: Optional[float] = Field(default=None, ge=3.0, le=50.0)
    emergency_pnl_velocity_pct: Optional[float] = Field(default=None, ge=2.0, le=20.0)
    auto_enabled: Optional[bool] = None
