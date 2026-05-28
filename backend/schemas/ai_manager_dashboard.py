"""Pydantic models for AI Manager dashboard API responses."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class LLMCallEntry(BaseModel):
    id: int
    call_id: str
    evaluation_cycle_id: str
    node_name: str
    timestamp: datetime
    model: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    success: bool
    urgency_tier: str
    action_returned: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    reasoning_preview: str | None = None
    attempt_number: int = Field(ge=1)


class LLMCallListResponse(BaseModel):
    calls: list[LLMCallEntry]
    next_cursor: str | None = None


class CapabilityStatusEntry(BaseModel):
    capability_key: str
    display_name: str
    enabled: bool
    status: Literal["healthy", "degraded", "failed", "disabled"]
    last_triggered_at: datetime | None = None
    trigger_count_session: int = Field(ge=0, default=0)
    next_trigger_condition: str
    countdown_seconds: int | None = Field(default=None, ge=0)
    armed: bool = False


class CapabilitiesResponse(BaseModel):
    capabilities: list[CapabilityStatusEntry]
    degradation_tier: int = Field(ge=0, le=4)
    evaluation_interval_s: int
    next_evaluation_in_s: int = Field(ge=0)


class CommentaryEntry(BaseModel):
    id: int
    generated_at: datetime
    summary_text: str
    regime_label: str
    commentary_type: Literal["template", "llm"]


class PositionHealth(BaseModel):
    symbol: str
    health_score: int = Field(ge=0, le=100)
    concern: str | None = None


class SweepSignal(BaseModel):
    symbol: str
    confidence: float = Field(ge=0, le=1)
    direction: str


class MarketInsightResponse(BaseModel):
    day_score: int | None = Field(default=None, ge=0, le=100)
    day_score_label: Literal["good", "neutral", "caution", "danger"] | None = None
    day_score_justification: str | None = None
    latest_commentary: CommentaryEntry | None = None
    regime: dict | None = None
    session: Literal["asia", "london", "new_york", "off_hours"] | None = None
    correlation_heat: float | None = Field(default=None, ge=0, le=1)
    active_sweeps: list[SweepSignal] = []
    positions_health: list[PositionHealth] = []


class AnalysisContextResponse(BaseModel):
    regime: dict | None = None
    mtf: dict | None = None
    correlation: dict | None = None
    orderbook: dict | None = None
    sweep_signals: list[SweepSignal] = []
    evaluation_cycle_id: str | None = None
    computed_at: datetime | None = None


class AttentionItem(BaseModel):
    id: str
    severity: Literal["critical", "warning", "info"]
    title: str
    description: str
    timestamp: datetime
    source: str


class ErrorResponse(BaseModel):
    error: str
    code: str
    details: dict | None = None
