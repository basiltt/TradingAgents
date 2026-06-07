"""MCP tool registry — TASK-P0-04.

Trading-free core. Declares the ToolGroup/SafetyClass enums, the `@tool`
decorator (self-registration), the capability-tier ordering, preset predicates,
and the registration-time deny-list. Tools register into `_REGISTRY` at import
time; `resolve_enabled` filters by persisted config + capability tier + backing
service availability.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel


class ToolGroup(str, Enum):
    """Authoritative, append-only tool-group taxonomy."""

    SCANS = "scans"
    ACCOUNTS = "accounts"
    POSITIONS = "positions"
    TRADES = "trades"
    PORTFOLIO = "portfolio"
    ANALYTICS = "analytics"
    SCHEDULED = "scheduled"
    STRATEGIES = "strategies"
    SYMBOLS = "symbols"
    BACKTEST = "backtest"
    DEBUG = "debug"
    OPTIMIZER = "optimizer"
    ADVANCED = "advanced"


class SafetyClass(str, Enum):
    """Risk class of a tool, mapped to the minimum capability tier required."""

    READ_ONLY = "read_only"
    BACKTEST = "backtest"
    LIVE_MONEY = "live_money"


# Capability tiers form an ordered ceiling (ADR-5). A tool whose SafetyClass
# maps to a tier rank <= the configured tier is allowed.
_TIER_RANK: dict[str, int] = {
    "READ_ONLY": 0,
    "BACKTEST": 1,
    "MUTATING_DEMO": 2,
    "LIVE_MONEY": 3,
}

# SafetyClass -> the minimum tier that may use it.
_SAFETY_MIN_TIER: dict[SafetyClass, str] = {
    SafetyClass.READ_ONLY: "READ_ONLY",
    SafetyClass.BACKTEST: "BACKTEST",
    SafetyClass.LIVE_MONEY: "LIVE_MONEY",
}

# Core read-only groups eligible for the Minimal preset.
_CORE_READ_GROUPS: frozenset[ToolGroup] = frozenset(
    {
        ToolGroup.SCANS,
        ToolGroup.ACCOUNTS,
        ToolGroup.POSITIONS,
        ToolGroup.TRADES,
        ToolGroup.PORTFOLIO,
        ToolGroup.ANALYTICS,
        ToolGroup.SCHEDULED,
        ToolGroup.STRATEGIES,
        ToolGroup.SYMBOLS,
    }
)

# Registration-time deny-list: service methods/endpoints that must NEVER be
# wrapped as a tool. The call-graph test (P0/P4) asserts no handler reaches them.
_DENY_METHODS: frozenset[str] = frozenset(
    {
        # config / token / kill-switch / audit writers
        "update_config",
        "regenerate_token",
        "set_token_hash",
        "bump_kill_epoch",
        # live scheduled-scan config writers (money sinks)
        "update_scheduled_scan",
        "create_scheduled_scan",
        "apply_auto_trade_config_atomic",
        # exchange order / leverage methods
        "place_order",
        "close_position",
        "set_leverage",
        "cancel_order",
    }
)

_NAME_RE = re.compile(r"^[a-z]+_[a-z_]+$")


@dataclass(frozen=True)
class ToolSpec:
    """Static description of a registered tool."""

    name: str
    group: ToolGroup
    handler: Callable[..., Any]
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    safety_class: SafetyClass
    mutating: bool
    exchange_facing: bool
    description: str


_REGISTRY: dict[str, ToolSpec] = {}


def tool(
    *,
    name: str,
    group: ToolGroup,
    input_schema: type[BaseModel],
    output_schema: type[BaseModel],
    safety_class: SafetyClass,
    mutating: bool = False,
    exchange_facing: bool = False,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a tool handler. Returns the handler unchanged.

    The handler's docstring becomes the agent-facing description (required).
    """

    def _decorate(handler: Callable[..., Any]) -> Callable[..., Any]:
        if not _NAME_RE.match(name):
            raise ValueError(
                f"invalid tool name {name!r} (must match {_NAME_RE.pattern})"
            )
        if name in _REGISTRY:
            raise ValueError(f"duplicate tool name {name!r}")
        description = (handler.__doc__ or "").strip()
        if not description:
            raise ValueError(f"tool {name!r} requires a non-empty docstring")
        _REGISTRY[name] = ToolSpec(
            name=name,
            group=group,
            handler=handler,
            input_schema=input_schema,
            output_schema=output_schema,
            safety_class=safety_class,
            mutating=mutating,
            exchange_facing=exchange_facing,
            description=description,
        )
        return handler

    return _decorate


def tier_allows(safety_class: SafetyClass, tier: str) -> bool:
    """True if a tool of `safety_class` may run at `tier` (the configured ceiling)."""
    min_tier = _SAFETY_MIN_TIER[safety_class]
    return _TIER_RANK[min_tier] <= _TIER_RANK.get(tier, -1)


def iter_specs() -> list[ToolSpec]:
    """Public, read-only snapshot of every registered tool.

    Used by the control-plane registry endpoint to render the full budget
    catalog (every tool, regardless of enabled state). Ordering is stable
    (group then name) so the operator UI is deterministic.
    """
    return sorted(_REGISTRY.values(), key=lambda s: (s.group.value, s.name))


# Reverse of _TIER_RANK for mapping a numeric ceiling back to a tier name.
_RANK_TIER: dict[int, str] = {rank: name for name, rank in _TIER_RANK.items()}


def required_tier(specs: list[ToolSpec]) -> str:
    """The minimum capability tier that allows EVERY spec in `specs`.

    A preset/selection is a complete intent: if it includes a BACKTEST tool the
    tier ceiling must be at least BACKTEST or the tool would be silently hidden.
    Returns "READ_ONLY" for an empty selection (the safe floor).
    """
    if not specs:
        return "READ_ONLY"
    needed = max(_TIER_RANK[_SAFETY_MIN_TIER[s.safety_class]] for s in specs)
    return _RANK_TIER[needed]


@dataclass(frozen=True)
class MCPConfigView:
    """The slice of mcp_config the registry needs to resolve the enabled set."""

    capability_tier: str
    enabled_groups: list[str]
    enabled_tools: dict[str, bool]


def resolve_enabled(
    config: MCPConfigView,
    *,
    available: Callable[[ToolGroup], bool],
    debug_allowed: bool = False,
) -> list[ToolSpec]:
    """Return the tools that should be advertised, applying:

    - most-restrictive group/individual resolution,
    - the capability-tier ceiling,
    - the allow_debug gate (DEBUG group hidden unless debug_allowed),
    - backing-service availability.
    """
    enabled_groups = set(config.enabled_groups)
    overrides = config.enabled_tools
    out: list[ToolSpec] = []
    for spec in _REGISTRY.values():
        # individual override wins (most restrictive)
        override = overrides.get(spec.name)
        if override is False:
            continue
        group_on = spec.group.value in enabled_groups
        if not (override is True or group_on):
            continue
        if spec.group is ToolGroup.DEBUG and not debug_allowed:
            continue
        if not tier_allows(spec.safety_class, config.capability_tier):
            continue
        if not available(spec.group):
            continue
        out.append(spec)
    return out


# --- Presets: predicates over registry metadata, not name lists (R-381) ---

def _minimal(spec: ToolSpec) -> bool:
    return spec.safety_class is SafetyClass.READ_ONLY and spec.group in _CORE_READ_GROUPS


def _read_only(spec: ToolSpec) -> bool:
    return spec.safety_class is SafetyClass.READ_ONLY and not spec.mutating


def _backtest_only(spec: ToolSpec) -> bool:
    return spec.safety_class in (SafetyClass.READ_ONLY, SafetyClass.BACKTEST) and (
        spec.group in (ToolGroup.BACKTEST, ToolGroup.OPTIMIZER) or _read_only(spec)
    )


def _standard(spec: ToolSpec) -> bool:
    # read-only suite + backtest, excluding advanced primitives and live-money
    return spec.safety_class is not SafetyClass.LIVE_MONEY and spec.group is not ToolGroup.ADVANCED


def _full(spec: ToolSpec) -> bool:
    return spec.safety_class is not SafetyClass.LIVE_MONEY


PRESETS: dict[str, Callable[[ToolSpec], bool]] = {
    "minimal": _minimal,
    "read_only": _read_only,
    "backtest_only": _backtest_only,
    "standard": _standard,
    "full": _full,
}
