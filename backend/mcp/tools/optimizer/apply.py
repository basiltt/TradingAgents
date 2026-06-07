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

import math
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


def _finite(v: Any) -> float:
    """Coerce to float, treating NaN/Inf as a ceiling breach (returns a value
    that fails every bound). NaN comparisons are always False, so NaN must be
    rejected explicitly or it would slip past `> ceiling` / `< floor` checks."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return math.inf  # non-numeric → fail the > ceiling check
    if not math.isfinite(f):
        return math.inf
    return f


def sanity_ceiling_ok(merged: dict[str, Any]) -> bool:
    """Hard non-overridable bounds. Returns False if any is breached.

    Fail-closed: a missing/None stop_loss_pct is treated as a breach (a live
    config with no stop loss at leverage must never pass the ceiling); NaN/Inf
    in any bounded field is also a breach (NaN comparisons silently pass `>`).
    """
    if _finite(merged.get("leverage", 0)) > _MAX_LEVERAGE:
        return False
    sl = merged.get("stop_loss_pct")
    if sl is None or _finite(sl) < _MIN_STOP_LOSS_PCT:
        return False
    if _finite(merged.get("capital_pct", 0)) > _MAX_CAPITAL_PCT:
        return False
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


def build_diff(prior: dict[str, Any], proposed: dict[str, Any]) -> dict[str, Any]:
    """Construct the proposal diff envelope stored in mcp_proposals.diff.

    Shape (consumed by both the drift-guard and the operator UI):
      {
        "before": <full prior config>,   # drift baseline + revert source
        "fields": { field: {"from": old, "to": new}, ... }  # per-field changes
      }
    Only sweepable fields that actually changed appear in `fields`. `before` is
    the COMPLETE prior config so the atomic apply can drift-check against it.
    """
    fields: dict[str, dict[str, Any]] = {}
    for key in SWEEPABLE_FIELDS:
        if key in proposed and proposed[key] != prior.get(key):
            fields[key] = {"from": prior.get(key), "to": proposed[key]}
    return {"before": dict(prior), "fields": fields}


def validate_full_config(config: dict[str, Any]) -> dict[str, Any]:
    """Run a COMPLETE config (not a patch) through the SAME ceiling + model gates.

    Used by revert: restoring a prior config must obey the absolute sanity
    ceiling exactly like a forward apply — a prior snapshot that exceeds the
    hard leverage/capital bounds (or has NaN/no stop loss) must never be written
    back to live config just because it was once stored.
    """
    if not sanity_ceiling_ok(config):
        raise ApplyRejected("config breaches an absolute sanity ceiling")
    model_input = dict(config)
    model_input.setdefault("account_id", config.get("account_id", "mcp-revert"))
    try:
        AutoTradeConfig(**model_input)
    except Exception as exc:  # noqa: BLE001
        raise ApplyRejected(f"config failed validation: {exc}") from exc
    return config
