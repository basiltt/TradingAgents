"""Pydantic v2 models for the debug API."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class DebugConfigUpdate(BaseModel):
    tracing_enabled: Optional[bool] = None
    retention_days: Optional[int] = Field(None, ge=1, le=3650)
    symbol_decision_cap: Optional[int] = Field(None, ge=0, le=100000)
