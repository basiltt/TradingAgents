"""Pydantic schemas for the web backend API — TASK-002."""

from __future__ import annotations

import re
from datetime import date
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

TICKER_RE = re.compile(r"^[A-Z0-9.\-^]{1,15}$")
CRYPTO_TICKER_RE = re.compile(r"^[A-Z0-9]{2,20}$")
MODEL_ID_RE = re.compile(r"^[a-zA-Z0-9._:/-]{1,100}$")
CUSTOM_LANG_RE = re.compile(r"^[A-Z][a-z]+([\s\-][A-Z][a-z]+)*$")

PRESET_LANGUAGES = frozenset(
    [
        "English",
        "Chinese",
        "Japanese",
        "Korean",
        "Hindi",
        "Spanish",
        "Portuguese",
        "French",
        "German",
        "Arabic",
        "Russian",
        "Custom",
    ]
)

VALID_PROVIDERS = frozenset(
    [
        "openai",
        "google",
        "anthropic",
        "xai",
        "deepseek",
        "qwen",
        "glm",
        "openrouter",
        "azure",
        "ollama",
    ]
)

VALID_VENDOR_CATEGORIES = frozenset(
    ["core_stock_apis", "technical_indicators", "fundamental_data", "news_data"]
)
VALID_VENDOR_VALUES = frozenset(["yfinance", "alpha_vantage"])


class AnalystType(str, Enum):
    MARKET = "market"
    SOCIAL = "social"
    NEWS = "news"
    FUNDAMENTALS = "fundamentals"


class CryptoAnalystType(str, Enum):
    CRYPTO_TECHNICAL = "crypto_technical"
    CRYPTO_DERIVATIVES = "crypto_derivatives"
    CRYPTO_NEWS = "crypto_news"


VALID_CRYPTO_INTERVALS = frozenset(["15", "60", "240", "D"])


class AnalysisRequest(BaseModel):
    ticker: str
    analysis_date: str
    asset_type: Optional[str] = "stock"
    interval: Optional[str] = None
    provider: Optional[str] = None
    deep_think_llm: Optional[str] = None
    quick_think_llm: Optional[str] = None
    backend_url: Optional[str] = None
    analysts: Optional[List[str]] = None
    research_depth: Optional[int] = Field(None, ge=1, le=5)
    output_language: Optional[str] = None
    data_vendors: Optional[Dict[str, str]] = None

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, v: str) -> str:
        v = v.strip().upper()
        if not TICKER_RE.match(v) and not CRYPTO_TICKER_RE.match(v):
            raise ValueError(
                f"Invalid ticker: must match stock or crypto pattern"
            )
        return v

    @field_validator("analysis_date")
    @classmethod
    def validate_analysis_date(cls, v: str) -> str:
        try:
            d = date.fromisoformat(v)
        except ValueError:
            raise ValueError("Invalid date format, expected YYYY-MM-DD")
        if d > date.today():
            raise ValueError("Analysis date cannot be in the future")
        return v

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_PROVIDERS:
            raise ValueError(f"Invalid provider: {v}")
        return v

    @field_validator("deep_think_llm", "quick_think_llm")
    @classmethod
    def validate_model_id(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not MODEL_ID_RE.match(v):
            raise ValueError(
                f"Invalid model ID: must match {MODEL_ID_RE.pattern}"
            )
        return v

    @field_validator("output_language")
    @classmethod
    def validate_output_language(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if v in PRESET_LANGUAGES:
            return v
        if len(v) > 30:
            raise ValueError("Output language must be at most 30 characters")
        if not CUSTOM_LANG_RE.match(v):
            raise ValueError(
                "Custom language must start with uppercase letter followed by lowercase, "
                "with optional space/hyphen-separated words"
            )
        return v

    @field_validator("data_vendors")
    @classmethod
    def validate_data_vendors(
        cls, v: Optional[Dict[str, str]]
    ) -> Optional[Dict[str, str]]:
        if v is None:
            return v
        for cat, val in v.items():
            if cat not in VALID_VENDOR_CATEGORIES:
                raise ValueError(f"Invalid vendor category: {cat}")
            if val not in VALID_VENDOR_VALUES:
                raise ValueError(f"Invalid vendor value: {val}")
        return v

    @model_validator(mode="after")
    def validate_asset_type_constraints(self):
        asset = self.asset_type or "stock"
        if asset == "crypto":
            if not CRYPTO_TICKER_RE.match(self.ticker):
                raise ValueError(f"Crypto ticker must match {CRYPTO_TICKER_RE.pattern}")
            if self.interval is None:
                raise ValueError("interval is required for crypto analysis")
            if self.interval not in VALID_CRYPTO_INTERVALS:
                raise ValueError(f"Invalid crypto interval: {self.interval}, must be one of {sorted(VALID_CRYPTO_INTERVALS)}")
            if self.analysts:
                valid = {e.value for e in CryptoAnalystType}
                for a in self.analysts:
                    if a not in valid:
                        raise ValueError(f"Invalid crypto analyst: {a}, must be one of {sorted(valid)}")
        elif asset == "stock":
            if self.analysts:
                valid = {e.value for e in AnalystType}
                for a in self.analysts:
                    if a not in valid:
                        raise ValueError(f"Invalid stock analyst: {a}, must be one of {sorted(valid)}")
        else:
            raise ValueError(f"Invalid asset_type: {asset}, must be 'stock' or 'crypto'")
        return self


class AnalysisCreateResponse(BaseModel):
    run_id: str
    status: str


class AnalysisResponse(BaseModel):
    run_id: str
    ticker: str
    analysis_date: str
    status: str
    config: Dict[str, Any]
    started_at: str
    completed_at: Optional[str] = None
    error: Optional[str] = None
    asset_type: Optional[str] = None


class AnalysisListItem(BaseModel):
    run_id: str
    ticker: str
    analysis_date: str
    status: str
    started_at: str
    completed_at: Optional[str] = None
    asset_type: Optional[str] = None


class AnalysisListResponse(BaseModel):
    items: List[AnalysisListItem]
    total: int
    page: int
    limit: int


class ConfigResponse(BaseModel):
    defaults: Dict[str, Any]
    overrides: Dict[str, Any]
    resolved: Dict[str, Any]


class ConfigUpdateRequest(BaseModel):
    overrides: Dict[str, Any]


class MemoryEntry(BaseModel):
    ticker: str
    date: str
    decision: str
    confidence: str
    status: str
    reasoning: Optional[str] = None


class MemoryListResponse(BaseModel):
    items: List[MemoryEntry]
    total: int
    page: int
    limit: int


class CheckpointResponse(BaseModel):
    exists: bool
    ticker: Optional[str] = None
    date: Optional[str] = None


class ErrorResponse(BaseModel):
    detail: str
    code: Optional[str] = None
