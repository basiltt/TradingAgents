"""Apply pipeline — TASK-P4-10 (the money path).

The ONLY route a swept config becomes live trading config — and it runs only
behind human approval in the control-plane. Three gates, in order:

  1. allow-list sanitize: accept ONLY known-safe sweepable AutoTradeConfig
     fields; reject anything else (fail-closed; a future live-enabling field
     can never slip through).
  2. absolute sanity ceiling: hard non-overridable bounds independent of the
     agent and the user's guardrails.
  3. merged-config validation: build the FULL prospective AutoTradeConfig
     (current ⊕ patch) and run the model's cross-field validators on THAT.

The actual DB write (read-merge-write under FOR UPDATE) lives in the control
plane / persistence layer; this module is the pure, unit-testable policy core.
"""
from __future__ import annotations

from typing import Any

from backend.schemas import AutoTradeConfig

# Explicit literal frozenset — NOT derived from the model, so a future
# live-enabling field is never auto-admitted (it must be classified by a human +
# the CI fail-on-new-field test).
SWEEPABLE_FIELDS: frozenset[str] = frozenset(
    {
        "direction",
        "leverage",
        "capital_pct",
        "take_profit_pct",
        "stop_loss_pct",
        "min_score",
        "confidence_filter",
        "signal_sides",
        "max_trades",
        "max_drawdown_pct",
        "execution_mode",
        "skip_if_positions_open",
        "fill_to_max_trades",
        "close_on_profit_pct",
        "breakeven_timeout_hours",
        "max_trade_duration_hours",
        "smart_drawdown_close",
        "trailing_profit_pct",
        "max_same_direction",
        "max_price_drift_pct",
        "max_same_sector",
        "max_signal_age_minutes",
        "target_goal_type",
        "target_goal_value",
        "adaptive_blacklist_enabled",
        "adaptive_blacklist_min_trades",
        "adaptive_blacklist_max_win_rate",
        "adaptive_blacklist_lookback_hours",
    }
)

# Absolute, non-overridable sanity bounds (independent of agent + user guardrails).
_MAX_LEVERAGE = 50
_MIN_STOP_LOSS_PCT = 1.0  # SL must keep at least this much distance
_MAX_CAPITAL_PCT = 50.0


class ApplyRejected(Exception):
    """Raised when a proposed config fails sanitize / ceiling / validation."""


def sanitize_patch(patch: dict[str, Any], *, reject_if_empty: bool = False) -> dict[str, Any]:
    """Keep only allow-listed sweepable fields; drop everything else."""
    clean = {k: v for k, v in patch.items() if k in SWEEPABLE_FIELDS}
    if reject_if_empty and not clean:
        raise ApplyRejected("proposed patch contains no applicable (sweepable) fields")
    return clean


def sanity_ceiling_ok(merged: dict[str, Any]) -> bool:
    """Hard non-overridable bounds. Returns False if any is breached."""
    if float(merged.get("leverage", 0)) > _MAX_LEVERAGE:
        return False
    sl = merged.get("stop_loss_pct")
    if sl is not None and float(sl) < _MIN_STOP_LOSS_PCT:
        return False
    if float(merged.get("capital_pct", 0)) > _MAX_CAPITAL_PCT:
        return False
    # TP must be above 0 and SL ordering sane (both > 0 enforced by the model)
    return True


def validate_merged_config(current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Build current ⊕ sanitized-patch, run sanitize -> ceiling -> AutoTradeConfig
    validators on the MERGED config. Returns the merged dict or raises."""
    clean = sanitize_patch(patch, reject_if_empty=True)
    merged = {**current, **clean}
    if not sanity_ceiling_ok(merged):
        raise ApplyRejected("merged config breaches an absolute sanity ceiling")
    # ensure an account_id is present for the model (carried from current)
    model_input = dict(merged)
    model_input.setdefault("account_id", current.get("account_id", "mcp-proposed"))
    try:
        AutoTradeConfig(**model_input)
    except Exception as exc:  # noqa: BLE001 — surface as a clean rejection
        raise ApplyRejected(f"merged config failed validation: {exc}") from exc
    return merged
