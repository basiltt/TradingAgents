"""Pydantic schemas for the web backend API — TASK-002."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

try:
    from croniter import croniter as _croniter_cls
except ImportError:
    _croniter_cls = None
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
        "nvidia",
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

PROVIDER_API_KEY_MAP = {
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "xai": "XAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "glm": "ZHIPU_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "azure": "AZURE_OPENAI_API_KEY",
}


class AnalystType(str, Enum):
    MARKET = "market"
    SOCIAL = "social"
    NEWS = "news"
    FUNDAMENTALS = "fundamentals"


class CryptoAnalystType(str, Enum):
    CRYPTO_TECHNICAL = "crypto_technical"
    CRYPTO_DERIVATIVES = "crypto_derivatives"
    CRYPTO_NEWS = "crypto_news"
    CRYPTO_FUNDAMENTALS = "crypto_fundamentals"
    CRYPTO_SOCIAL = "crypto_social"


VALID_CRYPTO_INTERVALS = frozenset(["15", "60", "240", "D"])

VALID_STOCK_AGENT_KEYS = frozenset([
    "market", "social", "news", "fundamentals",
    "bull_researcher", "bear_researcher", "research_manager",
    "trader", "compliance_officer",
    "aggressive_analyst", "neutral_analyst", "conservative_analyst",
    "portfolio_manager", "execution_monitor",
])

VALID_CRYPTO_AGENT_KEYS = frozenset([
    "crypto_technical", "crypto_derivatives", "crypto_news",
    "crypto_fundamentals", "crypto_social", "confluence_checker",
    "bull_researcher", "bear_researcher", "research_manager",
    "trader", "compliance_officer",
    "bull_analyst", "bear_analyst",
    "portfolio_manager", "execution_monitor",
])


class AnalysisRequest(BaseModel):
    ticker: str
    analysis_date: str
    asset_type: Optional[str] = "stock"
    interval: Optional[str] = None
    provider: Optional[str] = None
    llm_api_key: Optional[str] = Field(None, max_length=200)
    deep_think_llm: Optional[str] = None
    quick_think_llm: Optional[str] = None
    backend_url: Optional[str] = None
    analysts: Optional[List[str]] = None
    research_depth: Optional[int] = Field(None, ge=1, le=5)
    output_language: Optional[str] = None
    max_debate_rounds: Optional[int] = Field(None, ge=1, le=10)
    max_risk_discuss_rounds: Optional[int] = Field(None, ge=1, le=10)
    max_recur_limit: Optional[int] = Field(None, ge=1, le=500)
    checkpoint_enabled: Optional[bool] = None
    data_vendors: Optional[Dict[str, str]] = None
    workflow_mode: Optional[str] = None
    agent_model_overrides: Optional[Dict[str, str]] = None
    ta_prefilter_enabled: Optional[bool] = None
    ta_prefilter_threshold: Optional[int] = Field(None, ge=0, le=100)

    @field_validator("workflow_mode")
    @classmethod
    def validate_workflow_mode(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("quick_trade", "deep_analysis"):
            raise ValueError("workflow_mode must be 'quick_trade' or 'deep_analysis'")
        return v

    @field_validator("agent_model_overrides")
    @classmethod
    def validate_agent_model_overrides(
        cls, v: Optional[Dict[str, str]]
    ) -> Optional[Dict[str, str]]:
        if v is None:
            return v
        for agent_key, model_id in v.items():
            if not MODEL_ID_RE.match(model_id):
                raise ValueError(
                    f"Invalid model ID for agent '{agent_key}': must match {MODEL_ID_RE.pattern}"
                )
        return v

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, v: str) -> str:
        v = v.strip().upper()
        if not TICKER_RE.match(v) and not CRYPTO_TICKER_RE.match(v):
            raise ValueError(
                "Invalid ticker: must match stock or crypto pattern"
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

        if self.agent_model_overrides:
            valid_keys = VALID_CRYPTO_AGENT_KEYS if asset == "crypto" else VALID_STOCK_AGENT_KEYS
            for key in self.agent_model_overrides:
                if key not in valid_keys:
                    raise ValueError(
                        f"Invalid agent key '{key}' for {asset} analysis, "
                        f"must be one of {sorted(valid_keys)}"
                    )

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


class TradeEventResponse(BaseModel):
    id: int
    trade_id: str
    event_type: str
    old_status: Optional[str] = None
    new_status: Optional[str] = None
    fill_qty: Optional[float] = None
    fill_price: Optional[float] = None
    actor: str
    payload: dict = {}
    created_at: datetime


class TradeResponse(BaseModel):
    id: str
    account_id: str
    symbol: str
    side: str
    order_type: str
    qty: float
    filled_qty: Optional[float] = None
    entry_price: Optional[float] = None
    avg_fill_price: Optional[float] = None
    exit_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    leverage: int
    margin_mode: str
    position_idx: int = 0
    mark_price_at_open: Optional[float] = None
    capital_pct: Optional[float] = None
    base_capital: Optional[float] = None
    signal_direction: Optional[str] = None
    trade_direction: Optional[str] = None
    take_profit_pct: Optional[float] = None
    stop_loss_pct: Optional[float] = None
    status: str
    order_id: Optional[str] = None
    order_link_id: Optional[str] = None
    close_reason: Optional[str] = None
    close_rule_id: Optional[str] = None
    parent_trade_id: Optional[str] = None
    realized_pnl: Optional[float] = None
    realized_pnl_pct: Optional[float] = None
    fees: Optional[float] = None
    net_pnl: Optional[float] = None
    source: str
    source_id: Optional[int] = None
    version: int
    metadata: dict = {}
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class TradeDetailResponse(TradeResponse):
    events: list[TradeEventResponse] = []


class TradeListResponse(BaseModel):
    items: list[TradeResponse]
    cursor: Optional[str] = None
    has_more: bool
    total: Optional[int] = None


class TradeStatsResponse(BaseModel):
    total_trades: int
    open_count: int = 0
    win_rate: float
    avg_pnl: float
    total_pnl: float
    avg_hold_time: Optional[float] = None


class TradeCloseRequest(BaseModel):
    qty: Optional[float] = None
    close_reason: Optional[str] = Field(default="manual_single", max_length=128)

    @field_validator("qty")
    @classmethod
    def qty_must_be_positive(cls, v):
        if v is not None and v <= 0:
            raise ValueError("qty must be positive")
        return v

    @field_validator("close_reason")
    @classmethod
    def validate_close_reason(cls, v):
        allowed = {"manual_single", "stop_loss", "take_profit", "rule_triggered", "liquidation", "external"}
        if v is not None and v not in allowed:
            raise ValueError(f"close_reason must be one of {allowed}")
        return v


class AutoTradeConfig(BaseModel):
    """Per-account auto-trade configuration for market scans."""

    model_config = ConfigDict(extra="forbid")

    account_id: str = Field(..., min_length=1, max_length=64)
    direction: Literal["straight", "reverse"] = "straight"
    leverage: int = Field(default=20, ge=1, le=125)
    capital_pct: float = Field(default=5, gt=0, le=100)
    take_profit_pct: float = Field(default=150, gt=0, le=1000)
    stop_loss_pct: float = Field(default=100, gt=0, le=1000)
    min_score: float = Field(default=0, ge=0, le=10)
    confidence_filter: Literal["any", "high", "moderate", "low"] = "any"
    signal_sides: Literal["both", "buy", "sell"] = "both"
    max_trades: int = Field(default=999, ge=1, le=999)
    max_drawdown_pct: float = Field(default=100, ge=1, le=100)
    target_goal_type: Optional[Literal["trade_count", "profit_pct"]] = None
    target_goal_value: Optional[float] = Field(None, gt=0)
    execution_mode: Literal["immediate", "batch"] = "immediate"
    skip_if_positions_open: bool = False
    fill_to_max_trades: bool = False
    close_on_profit_pct: Optional[float] = Field(None, gt=0, le=100)
    breakeven_timeout_hours: Optional[float] = Field(None, gt=0, le=720)
    max_trade_duration_hours: Optional[float] = Field(None, gt=0, le=720)
    ai_manager_enabled: bool = False

    @model_validator(mode="after")
    def validate_target_goal(self) -> "AutoTradeConfig":
        if self.target_goal_type and not self.target_goal_value:
            raise ValueError("target_goal_value required when target_goal_type is set")
        if self.target_goal_value and not self.target_goal_type:
            raise ValueError("target_goal_type required when target_goal_value is set")
        if self.close_on_profit_pct and not self.target_goal_value:
            raise ValueError("close_on_profit_pct requires target_goal_value to be set")
        return self


class ScanRequest(BaseModel):
    analysis_date: str
    asset_type: Optional[str] = "crypto"
    interval: Optional[str] = "D"
    provider: Optional[str] = None
    llm_api_key: Optional[str] = Field(None, max_length=200)
    deep_think_llm: Optional[str] = None
    quick_think_llm: Optional[str] = None
    backend_url: Optional[str] = None
    analysts: Optional[List[str]] = None
    research_depth: Optional[int] = Field(None, ge=1, le=5)
    output_language: Optional[str] = None
    max_debate_rounds: Optional[int] = Field(None, ge=1, le=10)
    max_risk_discuss_rounds: Optional[int] = Field(None, ge=1, le=10)
    max_recur_limit: Optional[int] = Field(None, ge=1, le=500)
    checkpoint_enabled: Optional[bool] = None
    data_vendors: Optional[Dict[str, str]] = None
    max_parallel: Optional[int] = Field(None, ge=1, le=15)
    workflow_mode: Optional[str] = None
    agent_model_overrides: Optional[Dict[str, str]] = None
    ta_prefilter_enabled: Optional[bool] = None
    ta_prefilter_threshold: Optional[int] = Field(None, ge=0, le=100)
    auto_trade_configs: Optional[List["AutoTradeConfig"]] = None

    @field_validator("workflow_mode")
    @classmethod
    def validate_scan_workflow_mode(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("quick_trade", "deep_analysis"):
            raise ValueError("workflow_mode must be 'quick_trade' or 'deep_analysis'")
        return v

    @field_validator("agent_model_overrides")
    @classmethod
    def validate_scan_agent_model_overrides(
        cls, v: Optional[Dict[str, str]]
    ) -> Optional[Dict[str, str]]:
        if v is None:
            return v
        for agent_key, model_id in v.items():
            if not MODEL_ID_RE.match(model_id):
                raise ValueError(
                    f"Invalid model ID for agent '{agent_key}': must match {MODEL_ID_RE.pattern}"
                )
        return v

    @field_validator("analysis_date")
    @classmethod
    def validate_scan_date(cls, v: str) -> str:
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
    def validate_scan_analyst_type(self):
        asset = self.asset_type or "crypto"
        if asset not in ("stock", "crypto"):
            raise ValueError(f"Invalid asset_type: {asset}, must be 'stock' or 'crypto'")
        if self.analysts:
            if asset == "crypto":
                valid = {e.value for e in CryptoAnalystType}
            else:
                valid = {e.value for e in AnalystType}
            for a in self.analysts:
                if a not in valid:
                    raise ValueError(f"Invalid analyst for {asset}: {a}, must be one of {sorted(valid)}")

        if self.agent_model_overrides:
            valid_keys = VALID_CRYPTO_AGENT_KEYS if asset == "crypto" else VALID_STOCK_AGENT_KEYS
            for key in self.agent_model_overrides:
                if key not in valid_keys:
                    raise ValueError(
                        f"Invalid agent key '{key}' for {asset} scan, "
                        f"must be one of {sorted(valid_keys)}"
                    )

        return self


# ─────────────────────────────────────────────────────────────────────────────
# Scan result response schemas — strict validation so wrong values never reach
# the frontend. Any value outside the allowed sets is coerced to a safe default
# rather than passed through.
# ─────────────────────────────────────────────────────────────────────────────

class ScanDirection(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class ScanConfidence(str, Enum):
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"
    NONE = "none"


class ScanResultItem(BaseModel):
    ticker: str
    run_id: Optional[str] = None
    status: Literal["completed", "failed", "cancelled", "unknown"] = "unknown"
    direction: ScanDirection = ScanDirection.HOLD
    confidence: ScanConfidence = ScanConfidence.NONE
    score: int = Field(default=0, ge=-10, le=10)
    decision_summary: str = ""
    signal_source: str = "unknown"

    @field_validator("score", mode="before")
    @classmethod
    def clamp_score(cls, v: Any) -> int:
        try:
            v = int(v)
        except (TypeError, ValueError):
            return 0
        return max(-10, min(10, v))

    @field_validator("direction", mode="before")
    @classmethod
    def coerce_direction(cls, v: Any) -> str:
        if isinstance(v, str) and v.lower() in ("buy", "sell", "hold"):
            return v.lower()
        return "hold"

    @field_validator("confidence", mode="before")
    @classmethod
    def coerce_confidence(cls, v: Any) -> str:
        if isinstance(v, str) and v.lower() in ("high", "moderate", "low", "none"):
            return v.lower()
        return "none"


class ScanStatusResponse(BaseModel):
    scan_id: str
    status: Literal["running", "completed", "failed", "cancelled"]
    total: int = Field(ge=0)
    completed: int = Field(ge=0)
    failed: int = Field(ge=0)
    current_batch: int = Field(ge=0)
    total_batches: int = Field(ge=0)
    current_tickers: List[str] = []
    results: List[ScanResultItem] = []
    started_at: str = ""
    completed_at: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Trading Accounts schemas
# ─────────────────────────────────────────────────────────────────────────────


class CreateAccountRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=64)
    account_type: Literal["demo", "live"]
    api_key: str = Field(..., min_length=10)
    api_secret: str = Field(..., min_length=10)


class UpdateAccountRequest(BaseModel):
    label: Optional[str] = Field(None, min_length=1, max_length=64)
    is_active: Optional[bool] = None


class RotateCredentialsRequest(BaseModel):
    api_key: str = Field(..., min_length=10)
    api_secret: str = Field(..., min_length=10)



class PlaceTradeRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    symbol: str = Field(..., min_length=2, max_length=20)
    signal_direction: Literal["buy", "sell"]
    trade_direction: Literal["straight", "reverse"]
    leverage: int = Field(..., ge=1, le=125)
    take_profit_pct: float = Field(..., gt=0, le=1000)
    stop_loss_pct: float = Field(..., gt=0, le=1000)
    capital_pct: float = Field(..., gt=0, le=100)
    base_capital: float = Field(..., gt=0)

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        v = v.upper().strip()
        if not CRYPTO_TICKER_RE.match(v):
            raise ValueError("Invalid symbol format")
        return v


# ── Strategy Schemas ────────────────────────────────────────────

VALID_STRATEGY_CATEGORIES = frozenset(
    ["scalping", "intraday", "swing", "positional", "grid", "dca", "hedging", "arbitrage"]
)
VALID_STRATEGY_STATUSES = frozenset(["active", "paused", "archived", "draft"])

MAX_CONFIG_SIZE_BYTES = 65_536


class CreateStrategyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field("", max_length=2000)
    category: str = Field("swing")
    status: str = Field("draft")
    config: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Strategy name cannot be empty")
        return v

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        if v not in VALID_STRATEGY_CATEGORIES:
            raise ValueError(f"Invalid category: {v}. Must be one of: {', '.join(sorted(VALID_STRATEGY_CATEGORIES))}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in VALID_STRATEGY_STATUSES:
            raise ValueError(f"Invalid status: {v}. Must be one of: {', '.join(sorted(VALID_STRATEGY_STATUSES))}")
        return v

    @field_validator("config")
    @classmethod
    def validate_config_size(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if len(json.dumps(v)) > MAX_CONFIG_SIZE_BYTES:
            raise ValueError("Config too large (max 64KB)")
        return v


class UpdateStrategyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    category: Optional[str] = None
    status: Optional[str] = None
    config: Optional[Dict[str, Any]] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Strategy name cannot be empty")
        return v

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_STRATEGY_CATEGORIES:
            raise ValueError(f"Invalid category: {v}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_STRATEGY_STATUSES:
            raise ValueError(f"Invalid status: {v}")
        return v

    @field_validator("config")
    @classmethod
    def validate_config_size(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if v is not None:
            if len(json.dumps(v)) > MAX_CONFIG_SIZE_BYTES:
                raise ValueError("Config too large (max 64KB)")
        return v


# ── Scheduled Scans ──────────────────────────────────────────────────


class ScheduleType(str, Enum):
    ONCE = "once"
    INTERVAL = "interval"
    DAILY = "daily"
    WEEKLY = "weekly"
    CRON = "cron"


VALID_TIMEZONES: Optional[frozenset] = None


def _get_valid_timezones() -> frozenset:
    global VALID_TIMEZONES
    if VALID_TIMEZONES is None:
        import pytz
        VALID_TIMEZONES = frozenset(pytz.all_timezones)
    return VALID_TIMEZONES


VALID_DAYS_OF_WEEK = frozenset(["mon", "tue", "wed", "thu", "fri", "sat", "sun"])
SCHEDULE_NAME_RE = re.compile(r"^[\w\s\-.,!?()&/:]+$")


class ScheduleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_at: Optional[str] = None
    interval_minutes: Optional[int] = Field(None, ge=15, le=10080)
    time: Optional[str] = None
    days: Optional[List[str]] = None
    day: Optional[str] = None
    cron_expression: Optional[str] = None

    @field_validator("run_at")
    @classmethod
    def validate_run_at(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            try:
                datetime.fromisoformat(v.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                raise ValueError("run_at must be a valid ISO 8601 datetime string")
        return v

    @field_validator("time")
    @classmethod
    def validate_time(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if not re.match(r"^\d{2}:\d{2}$", v):
                raise ValueError("time must be in HH:MM format")
            h, m = map(int, v.split(":"))
            if h > 23 or m > 59:
                raise ValueError("Invalid time value")
        return v

    @field_validator("days")
    @classmethod
    def validate_days(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None:
            if not v:
                raise ValueError("days list cannot be empty")
            invalid = set(d.lower() for d in v) - VALID_DAYS_OF_WEEK
            if invalid:
                raise ValueError(f"Invalid days: {invalid}")
            v = [d.lower() for d in v]
        return v

    @field_validator("day")
    @classmethod
    def validate_day(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if v.lower() not in VALID_DAYS_OF_WEEK:
                raise ValueError(f"Invalid day: {v}")
            v = v.lower()
        return v

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            parts = v.split()
            if len(parts) != 5:
                raise ValueError("Cron expression must have exactly 5 fields")
            dangerous = re.compile(r"[@;|&`$]")
            if dangerous.search(v):
                raise ValueError("Cron expression contains invalid characters")
            if _croniter_cls is not None and not _croniter_cls.is_valid(v):
                raise ValueError("Invalid cron expression")
        return v


class CreateScheduledScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255)
    schedule_type: ScheduleType
    schedule_config: ScheduleConfig
    scan_config: Dict[str, Any]
    timezone: str = Field(default="UTC")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be empty")
        v = re.sub(r"[\x00-\x1f\x7f]", "", v)
        if len(v) > 255:
            raise ValueError("Name too long after sanitization")
        if not SCHEDULE_NAME_RE.match(v):
            raise ValueError("Name contains invalid characters")
        return v

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        if v not in _get_valid_timezones():
            raise ValueError(f"Invalid timezone: {v}")
        return v

    @field_validator("scan_config")
    @classmethod
    def validate_scan_config(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if len(json.dumps(v)) > MAX_CONFIG_SIZE_BYTES:
            raise ValueError("scan_config too large (max 64KB)")
        if "provider" in v and v["provider"] is not None:
            if v["provider"] not in VALID_PROVIDERS:
                raise ValueError(f"Invalid provider: {v['provider']}")
        if "workflow_mode" in v and v["workflow_mode"] is not None:
            if v["workflow_mode"] not in ("quick_trade", "deep_analysis"):
                raise ValueError("workflow_mode must be 'quick_trade' or 'deep_analysis'")
        for model_key in ("deep_think_llm", "quick_think_llm"):
            if model_key in v and v[model_key] is not None:
                if not MODEL_ID_RE.match(v[model_key]):
                    raise ValueError(f"Invalid model ID for {model_key}")
        if "research_depth" in v and v["research_depth"] is not None:
            if not (1 <= int(v["research_depth"]) <= 5):
                raise ValueError("research_depth must be between 1 and 5")
        if "max_debate_rounds" in v and v["max_debate_rounds"] is not None:
            if not (1 <= int(v["max_debate_rounds"]) <= 10):
                raise ValueError("max_debate_rounds must be between 1 and 10")
        if "max_risk_discuss_rounds" in v and v["max_risk_discuss_rounds"] is not None:
            if not (1 <= int(v["max_risk_discuss_rounds"]) <= 10):
                raise ValueError("max_risk_discuss_rounds must be between 1 and 10")
        if "max_parallel" in v and v["max_parallel"] is not None:
            if not (1 <= int(v["max_parallel"]) <= 25):
                raise ValueError("max_parallel must be between 1 and 25")
        if "analysts" in v and v["analysts"] is not None:
            asset = v.get("asset_type", "crypto")
            valid = {e.value for e in CryptoAnalystType} if asset == "crypto" else {e.value for e in AnalystType}
            for a in v["analysts"]:
                if a not in valid:
                    raise ValueError(f"Invalid analyst: {a}")
        if "interval" in v and v["interval"] is not None:
            if v["interval"] not in VALID_CRYPTO_INTERVALS:
                raise ValueError(f"Invalid interval: {v['interval']}")
        if "auto_trade_configs" in v and v["auto_trade_configs"] is not None:
            if not isinstance(v["auto_trade_configs"], list):
                raise ValueError("auto_trade_configs must be a list")
            for i, cfg in enumerate(v["auto_trade_configs"]):
                try:
                    AutoTradeConfig(**cfg)
                except Exception as e:
                    raise ValueError(f"auto_trade_configs[{i}]: {e}")
        return v

    @model_validator(mode="after")
    def validate_type_config(self) -> "CreateScheduledScanRequest":
        cfg = self.schedule_config
        t = self.schedule_type
        if t == ScheduleType.ONCE:
            if not cfg.run_at:
                raise ValueError("once schedule requires run_at")
        elif t == ScheduleType.INTERVAL:
            if cfg.interval_minutes is None:
                raise ValueError("interval schedule requires interval_minutes")
        elif t == ScheduleType.DAILY:
            if not cfg.time:
                raise ValueError("daily schedule requires time")
            if cfg.days is None:
                cfg.days = list(VALID_DAYS_OF_WEEK)
        elif t == ScheduleType.WEEKLY:
            if not cfg.day or not cfg.time:
                raise ValueError("weekly schedule requires day and time")
        elif t == ScheduleType.CRON:
            if not cfg.cron_expression:
                raise ValueError("cron schedule requires cron_expression")
        return self


class UpdateScheduledScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    schedule_type: Optional[ScheduleType] = None
    schedule_config: Optional[ScheduleConfig] = None
    scan_config: Optional[Dict[str, Any]] = None
    timezone: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            v = re.sub(r"[\x00-\x1f\x7f]", "", v)
            if not v:
                raise ValueError("Name cannot be empty")
            if not SCHEDULE_NAME_RE.match(v):
                raise ValueError("Name contains invalid characters")
        return v

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in _get_valid_timezones():
            raise ValueError(f"Invalid timezone: {v}")
        return v

    @field_validator("scan_config")
    @classmethod
    def validate_scan_config(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if v is not None:
            if len(json.dumps(v)) > MAX_CONFIG_SIZE_BYTES:
                raise ValueError("scan_config too large (max 64KB)")
            # Reuse the same field validation as CreateScheduledScanRequest
            CreateScheduledScanRequest.validate_scan_config(v)
        return v


class ScheduledScanResponse(BaseModel):
    id: str
    name: str
    schedule_type: str
    schedule_config: Any
    scan_config: Any
    status: str
    timezone: str
    next_run_at: Optional[str] = None
    last_run_at: Optional[str] = None
    last_scan_id: Optional[str] = None
    consecutive_failures: int = 0
    is_running: bool = False
    created_at: str
    updated_at: str


class ScheduleExecutionResponse(BaseModel):
    id: int
    schedule_id: str
    scan_id: Optional[str] = None
    status: str
    started_at: str
    completed_at: Optional[str] = None
    error_message: Optional[str] = None


# ── Close Positions Schemas ──────────────────────────────────────

VALID_TRIGGER_TYPES = frozenset([
    "BALANCE_BELOW", "BALANCE_ABOVE",
    "EQUITY_DROP_PCT", "EQUITY_RISE_PCT",
    "PNL_BELOW", "PNL_ABOVE",
    "BREAKEVEN_TIMEOUT", "MAX_DURATION",
])

PCT_TRIGGER_TYPES = frozenset(["EQUITY_DROP_PCT", "EQUITY_RISE_PCT"])


class CreateCloseRuleRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    trigger_type: str
    threshold_value: str
    reference_value: Optional[str] = None

    @field_validator("trigger_type")
    @classmethod
    def validate_trigger_type(cls, v: str) -> str:
        if v not in VALID_TRIGGER_TYPES:
            raise ValueError(f"Invalid trigger_type: {v}. Must be one of: {', '.join(sorted(VALID_TRIGGER_TYPES))}")
        return v

    @field_validator("threshold_value")
    @classmethod
    def validate_threshold(cls, v: str) -> str:
        from decimal import Decimal as D, InvalidOperation
        try:
            val = D(v)
        except (InvalidOperation, ValueError):
            raise ValueError("threshold_value must be a valid number")
        if val <= 0:
            raise ValueError("threshold_value must be positive")
        if val > D("10000000"):
            raise ValueError("threshold_value exceeds maximum (10,000,000)")
        return v

    @model_validator(mode="after")
    def validate_pct_bounds(self) -> "CreateCloseRuleRequest":
        from decimal import Decimal as D
        if self.trigger_type in PCT_TRIGGER_TYPES:
            val = D(self.threshold_value)
            if val > D("100"):
                raise ValueError("Percentage threshold must be between 0.01 and 100")
        return self


class UpdateCloseRuleRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    trigger_type: Optional[str] = None
    threshold_value: Optional[str] = None
    reference_value: Optional[str] = None
    status: Optional[str] = None

    @field_validator("trigger_type")
    @classmethod
    def validate_trigger_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_TRIGGER_TYPES:
            raise ValueError(f"trigger_type must be one of: {', '.join(VALID_TRIGGER_TYPES)}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("active", "paused"):
            raise ValueError("status must be 'active' or 'paused'")
        return v

    @field_validator("threshold_value")
    @classmethod
    def validate_threshold(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        from decimal import Decimal as D, InvalidOperation
        try:
            val = D(v)
        except (InvalidOperation, ValueError):
            raise ValueError("threshold_value must be a valid number")
        if val <= 0:
            raise ValueError("threshold_value must be positive")
        return v

    @model_validator(mode="after")
    def validate_pct_bounds(self) -> "UpdateCloseRuleRequest":
        if self.trigger_type and self.trigger_type in ("EQUITY_DROP_PCT", "EQUITY_RISE_PCT") and self.threshold_value:
            from decimal import Decimal as D
            val = D(self.threshold_value)
            if val > D("100"):
                raise ValueError("Percentage threshold must be between 0.01 and 100")
        return self


# ── Trading Cycles ──────────────────────────────────────────────

class CreateCycleRequest(BaseModel):
    account_id: str
    scan_id: str
    trade_direction: Literal["straight", "reverse"]
    leverage: int = Field(ge=1, le=125)
    capital_pct: float = Field(gt=0, le=100)
    take_profit_pct: Optional[float] = Field(default=None, gt=0, le=1000)
    stop_loss_pct: Optional[float] = Field(default=None, gt=0, le=1000)
    min_score: int = Field(default=3, ge=-10, le=10)
    min_confidence: Literal["none", "low", "moderate", "high"] = "moderate"
    signal_filter: Literal["buy", "sell", "both"] = "both"
    max_trades: int = Field(default=5, ge=1, le=20)
    target_type: Literal["percentage", "amount"]
    target_value: float = Field(gt=0, le=10_000_000)
    max_drawdown_pct: float = Field(gt=0, le=100)

    @model_validator(mode="after")
    def check_aggregate_capital(self) -> "CreateCycleRequest":
        if self.capital_pct * self.max_trades > 100:
            raise ValueError("capital_pct × max_trades exceeds 100%")
        return self


class CycleTradeResponse(BaseModel):
    id: int
    symbol: str
    side: str
    order_link_id: Optional[str] = None
    qty: Optional[float] = None
    entry_price: Optional[float] = None
    status: Literal["pending", "submitted", "filled", "failed", "cancelled"]
    error_msg: Optional[str] = None
    created_at: datetime
    filled_at: Optional[datetime] = None


class CycleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: Literal["pending", "placing_trades", "running", "stopping", "completed", "stopped", "failed"]
    account_id: str
    scan_id: Optional[str] = None
    trade_direction: str = ""
    leverage: int = 1
    target_value: float = 0
    max_drawdown_pct: float = 0
    trades_placed: int
    trades_failed: int
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    stop_reason: Optional[str] = None


class CycleDetail(CycleResponse):
    trades: list[CycleTradeResponse] = []
    trade_direction: str
    leverage: int
    capital_pct: float
    take_profit_pct: Optional[float] = None
    stop_loss_pct: Optional[float] = None
    min_score: int
    min_confidence: str
    signal_filter: str
    max_trades: int
    target_type: str
    target_value: float
    max_drawdown_pct: float
    initial_equity: Optional[float] = None
    final_pnl: Optional[float] = None


class DryRunResponse(BaseModel):
    qualifying_symbols: list[str]
    estimated_trades: int
    balance_above_threshold: float
    balance_below_threshold: float
    estimated_capital_per_trade: float
    total_capital_pct: float
    current_equity: float
    warnings: list[str]


class FilterPreviewResponse(BaseModel):
    qualifying_count: int
    symbols: list[str]
    direction_breakdown: Dict[str, int]


class PaginatedCycleList(BaseModel):
    items: list[CycleResponse]
    total: int
    offset: int
    limit: int
